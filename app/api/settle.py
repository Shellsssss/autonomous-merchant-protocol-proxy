import time
import uuid
from datetime import datetime, timezone
from typing import Any
from fastapi import APIRouter, Header, HTTPException, status
from app.config import get_settings
from app.core.idempotency import (
    IdempotencyConflictError,
    IdempotencyLedger,
    ReplayDetectedError,
)
from app.core.inventory import (
    InventoryError,
)
from app.models import (
    PaymentOrderResult,
    PaymentSettlementRequest,
    PaymentSettlementResult,
    PaymentVerificationRequest,
    PaymentVerificationResult,
    SettlementRequest,
    SettlementResult,
    InventoryCommitRequest,
    InventoryCommitResult,
    FulfillmentReceipt,
    FulfillmentRequest,
    FulfillmentResult,
)
from app.services.razorpay_adapter import (
    RazorpayError,
    razorpay_adapter,
)
from app.core.transaction import TransactionState
from app.core.transaction_store import transaction_store
from app.api.negotiate import inventory
from app.services.receipt_store import receipt_store
from app.services.deal_store import deal_store

router = APIRouter(
    prefix="/api/v1/agent",
    tags=["Agent Commerce"],
)

# Settlement idempotency ledger.
# 
# This is deliberately separate from the inventory manager.
# Its responsibility is preventing duplicate payment execution.
settlement_ledger = IdempotencyLedger(ttl_seconds=300)
payment_verification_ledger = IdempotencyLedger(ttl_seconds=300)
payment_settlement_ledger = IdempotencyLedger(ttl_seconds=300)

def _receipt_digest(
    *,
    transaction_id: str,
    payment_id: str,
    amount: int,
    currency: str,
) -> str:
    """
    Generate a deterministic receipt digest.

    The digest gives Mission Control a compact integrity identifier
    for the settlement result.
    """
    import hashlib

    payload = (
        f"{transaction_id}|"
        f"{payment_id}|"
        f"{amount}|"
        f"{currency}"
    )

    return hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()

def _get_hold_for_transaction(
    transaction_id: str,
    hold_token: str,
):
    """
    Locate and validate the inventory hold belonging to a transaction.

    The inventory implementation is currently owned by the
    negotiation module, so we import its shared instance here.
    """
    from app.api.negotiate import inventory

    try:
        hold = inventory.get_hold(
            hold_token,
        )
    except InventoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": exc.code,
                "message": exc.message,
            },
        )

    if hold.transaction_id != transaction_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "HOLD_TRANSACTION_MISMATCH",
                "message": (
                    "Inventory hold does not belong to "
                    "the requested transaction."
                ),
            },
        )

    if hold.state != "HELD":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "INVALID_HOLD_STATE",
                "message": (
                    f"Inventory hold is in state "
                    f"'{hold.state}'."
                ),
            },
        )

    return hold

@router.post(
    "/settle",
    response_model=PaymentOrderResult,
    status_code=status.HTTP_200_OK,
)
async def settle(
    request: SettlementRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
) -> SettlementResult:
    """
    Settle an approved AMPP transaction.

    Security boundary:

        Settlement request
              ↓
        Idempotency check
              ↓
        Nonce replay check
              ↓
        Inventory hold validation
              ↓
        Razorpay payment
              ↓
        Inventory commit
              ↓
        Signed/integrity receipt

    The payment provider is reached only after all local security
    checks have passed.
    """
    settings = get_settings()

    # 1. Require idempotency key
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "IDEMPOTENCY_KEY_REQUIRED",
                "message": (
                    "The Idempotency-Key header is required "
                    "for settlement."
                ),
            },
        )

    # 2. Construct the idempotency payload.
    #
    # Do NOT validate the hold before checking idempotency.
    # A repeated idempotency key must be able to return the
    # original settlement result even after the hold is committed.
    settlement_payload: dict[str, Any] = {
        "transaction_id": request.transaction_id,
        "hold_token": request.hold_token,
    }

    # 3. Execute the payment exactly once
    # 
    #    existing key + same payload → cached response
    #    existing key + different payload → conflict
    #    new key + used nonce → replay
    #    new key + new nonce → execute operation
    def payment_operation() -> dict[str, Any]:
        """
        Operation protected by the idempotency ledger.

        This function is the only place where the settlement flow
        invokes Razorpay.

        Hold validation happens here, after the idempotency
        ledger has determined that this is a genuinely new
        settlement request.
        """

        # Validate the inventory hold only for a new settlement.
        hold = _get_hold_for_transaction(
            transaction_id=request.transaction_id,
            hold_token=request.hold_token,
        )

        from app.services.deal_store import get_deal

        deal = get_deal(
            request.transaction_id,
        )

        if deal is None:
            raise RazorpayError(
                "DEAL_NOT_FOUND",
                "No negotiated deal exists for this transaction.",
            )

        if deal.hold_token != request.hold_token:
            raise RazorpayError(
                "HOLD_TOKEN_MISMATCH",
                "Settlement hold token does not match the deal.",
            )

        transaction = transaction_store.get(request.transaction_id)
        if transaction.state != TransactionState.HELD:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "INVALID_TRANSACTION_STATE",
                    "message": (
                        "Settlement can only begin for a held transaction."
                    ),
                },
            )

        transaction_store.update_state(
            request.transaction_id,
            TransactionState.PAYMENT_PENDING,
            timestamp=int(time.time()),
            reason="Settlement request accepted; payment verification pending.",
        )

        order = razorpay_adapter.create_order(
            transaction_id=request.transaction_id,
            amount=deal.total_amount,
            currency=deal.currency,
        )

        return {
            "payment_order_id": order.order_id,
            "amount": deal.total_amount,
            "currency": deal.currency,
        }

    # Check for an existing idempotent settlement BEFORE validating
    # the inventory hold. A cached settlement must be returned even
    # though its inventory hold has already been committed.
    try:
        cached_payment = settlement_ledger.get_for_payload(
            idempotency_key,
            settlement_payload,
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": exc.code,
                "message": exc.message,
            },
        )

    if cached_payment is not None:
        return PaymentOrderResult(
            transaction_id=request.transaction_id,
            payment_id=cached_payment["payment_order_id"],
            status="PAYMENT_PENDING",
            amount=cached_payment["amount"],
            currency=cached_payment["currency"],
        )

    try:
        payment = settlement_ledger.execute(
            key=idempotency_key,
            payload=settlement_payload,
            nonce=request.nonce,
            timestamp=int(
                datetime.now(
                    timezone.utc,
                ).timestamp()
            ),
            operation=payment_operation,
        )

        transaction = transaction_store.get(
            request.transaction_id
        )
        transaction_store.update(
            transaction.model_copy(
                update={
                    "payment_order_id": payment["payment_order_id"],
                    "updated_at": int(time.time()),
                }
            )
        )
    except ReplayDetectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": exc.code,
                "message": exc.message,
            },
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": exc.code,
                "message": exc.message,
            },
        )
    except RazorpayError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": exc.code,
                "message": exc.message,
            },
        )

    # 5. Generate settlement receipt
    receipt_digest = _receipt_digest(
        transaction_id=request.transaction_id,
        payment_id=payment["payment_order_id"],
        amount=payment["amount"],
        currency=payment["currency"],
    )

    return PaymentOrderResult(
        transaction_id=request.transaction_id,
        payment_id=payment["payment_order_id"],
        status="PAYMENT_PENDING",
        amount=payment["amount"],
        currency=payment["currency"],
    )

@router.post("/verify-payment", response_model=PaymentVerificationResult)
def verify_payment(
    request: PaymentVerificationRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
):
    payload = {
        "transaction_id": request.transaction_id,
        "order_id": request.order_id,
        "payment_id": request.payment_id,
        "signature": request.signature,
    }

    def payment_verification_operation():
        transaction = transaction_store.get(request.transaction_id)
        if transaction.state != TransactionState.PAYMENT_PENDING:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "INVALID_TRANSACTION_STATE",
                    "message": (
                        f"Payment verification requires PAYMENT_PENDING state, "
                        f"but transaction is {transaction.state.value}."
                    ),
                },
            )

        if not transaction.payment_order_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "PAYMENT_ORDER_NOT_FOUND",
                    "message": "Transaction does not have a payment order.",
                },
            )

        if request.order_id != transaction.payment_order_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "PAYMENT_ORDER_MISMATCH",
                    "message": "Payment order does not match the transaction.",
                },
            )

        try:
            valid_signature = razorpay_adapter.verify_payment_signature(
                order_id=request.order_id,
                payment_id=request.payment_id,
                signature=request.signature,
            )
        except RazorpayError as exc:
            raise HTTPException(
                status_code=500,
                detail={
                    "code": exc.code,
                    "message": exc.message,
                },
            ) from exc

        if not valid_signature:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "INVALID_PAYMENT_SIGNATURE",
                    "message": "Payment signature verification failed.",
                },
            )

        transaction = transaction_store.get(request.transaction_id)
        updated_transaction = transaction.model_copy(
            update={
                "payment_id": request.payment_id,
                "updated_at": int(time.time()),
            }
        )

        transaction_store.update(updated_transaction)
        transaction_store.update_state(
            request.transaction_id,
            TransactionState.PAYMENT_VERIFIED,
            timestamp=int(time.time()),
            reason="Payment signature verified.",
            metadata={
                "payment_id": request.payment_id,
                "payment_order_id": request.order_id,
            },
        )

        return {
            "transaction_id": request.transaction_id,
            "payment_id": request.payment_id,
            "status": "PAYMENT_VERIFIED",
        }

    try:
        result = payment_verification_ledger.execute(
            key=idempotency_key,
            payload=payload,
            nonce=idempotency_key,
            timestamp=int(time.time()),
            operation=payment_verification_operation,
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": exc.code,
                "message": exc.message,
            },
        ) from exc

    return PaymentVerificationResult(**result)

@router.post(
    "/settle-payment",
    response_model=PaymentSettlementResult,
)
def settle_payment(request: PaymentSettlementRequest):
    transaction = transaction_store.get(request.transaction_id)
    if transaction.state != TransactionState.PAYMENT_VERIFIED:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INVALID_TRANSACTION_STATE",
                "message": (
                    "Payment settlement requires PAYMENT_VERIFIED state, "
                    f"but transaction is {transaction.state.value}."
                ),
            },
        )

    if transaction.payment_id != request.payment_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PAYMENT_MISMATCH",
                "message": "Payment ID does not match the verified transaction.",
            },
        )

    transaction_store.update_state(
        request.transaction_id,
        TransactionState.SETTLING,
        timestamp=int(time.time()),
        reason="Verified payment submitted for settlement.",
        metadata={
            "payment_id": request.payment_id,
        },
    )

    transaction_store.update_state(
        request.transaction_id,
        TransactionState.SETTLED,
        timestamp=int(time.time()),
        reason="Payment settlement completed.",
        metadata={
            "payment_id": request.payment_id,
        },
    )

    return PaymentSettlementResult(
        transaction_id=request.transaction_id,
        payment_id=request.payment_id,
        status="SETTLED",
    )

@router.post(
    "/commit-inventory",
    response_model=InventoryCommitResult,
)
def commit_inventory(request: InventoryCommitRequest):
    transaction = transaction_store.get(request.transaction_id)
    if transaction.state != TransactionState.SETTLED:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INVALID_TRANSACTION_STATE",
                "message": (
                    "Inventory commitment requires SETTLED state, "
                    f"but transaction is {transaction.state.value}."
                ),
            },
        )

    hold = _get_hold_for_transaction(
        transaction_id=request.transaction_id,
        hold_token=request.hold_token,
    )

    try:
        inventory.commit_hold(request.hold_token)
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INVENTORY_COMMIT_FAILED",
                "message": str(exc),
            },
        ) from exc

    transaction_store.update_state(
        request.transaction_id,
        TransactionState.INVENTORY_COMMITTED,
        timestamp=int(time.time()),
        reason="Inventory hold committed after successful payment settlement.",
        metadata={
            "hold_token": request.hold_token,
        },
    )

    return InventoryCommitResult(
        transaction_id=request.transaction_id,
        status="INVENTORY_COMMITTED",
    )

@router.post(
    "/fulfill",
    response_model=FulfillmentResult,
)
def fulfill_transaction(request: FulfillmentRequest):
    transaction = transaction_store.get(request.transaction_id)
    if transaction.state != TransactionState.INVENTORY_COMMITTED:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INVALID_TRANSACTION_STATE",
                "message": (
                    "Fulfillment requires INVENTORY_COMMITTED state, "
                    f"but transaction is {transaction.state.value}."
                ),
            },
        )

    if not transaction.payment_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PAYMENT_NOT_FOUND",
                "message": "Transaction does not have a verified payment.",
            },
        )

    deal = deal_store.get(request.transaction_id)
    if deal.hold_token != request.hold_token:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "HOLD_TOKEN_MISMATCH",
                "message": "Hold token does not match the transaction deal.",
            },
        )

    receipt_id = f"receipt_{uuid.uuid4().hex}"
    issued_at = int(time.time())

    receipt_digest = _receipt_digest(
        transaction_id=request.transaction_id,
        payment_id=transaction.payment_id,
        amount=deal.total_amount,
        currency=deal.currency,
    )

    receipt = FulfillmentReceipt(
        receipt_id=receipt_id,
        transaction_id=request.transaction_id,
        merchant_id=transaction.merchant_id,
        payment_id=transaction.payment_id,
        amount=deal.total_amount,
        currency=deal.currency,
        sku=deal.sku,
        quantity=deal.quantity,
        issued_at=issued_at,
        receipt_digest=receipt_digest,
    )

    receipt_store.create(receipt)
    transaction_store.update(
        transaction.model_copy(
            update={
                "receipt_id": receipt_id,
                "updated_at": issued_at,
            }
        )
    )

    transaction_store.update_state(
        request.transaction_id,
        TransactionState.COMPLETED,
        timestamp=issued_at,
        reason="Fulfillment receipt generated after inventory commitment.",
        metadata={
            "receipt_id": receipt_id,
            "receipt_digest": receipt_digest,
        },
    )

    return FulfillmentResult(
        transaction_id=request.transaction_id,
        receipt_id=receipt_id,
        status="COMPLETED",
        receipt_digest=receipt_digest,
    )