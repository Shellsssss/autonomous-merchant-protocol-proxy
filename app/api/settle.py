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
    SettlementRequest,
    SettlementResult,
)
from app.services.razorpay_adapter import (
    RazorpayError,
    razorpay_adapter,
)

router = APIRouter(
    prefix="/api/v1/agent",
    tags=["Agent Commerce"],
)

# Settlement idempotency ledger.
# 
# This is deliberately separate from the inventory manager.
# Its responsibility is preventing duplicate payment execution.
settlement_ledger = IdempotencyLedger(
    ttl_seconds=300,
)

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
    response_model=SettlementResult,
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

        order = razorpay_adapter.create_order(
            transaction_id=request.transaction_id,
            amount=deal.total_amount,
            currency=deal.currency,
        )

        return {
            "payment_id": order.order_id,
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
        return SettlementResult(
            transaction_id=request.transaction_id,
            payment_id=cached_payment["payment_id"],
            status="SETTLED",
            amount=cached_payment["amount"],
            currency=cached_payment["currency"],
            receipt_digest=_receipt_digest(
                transaction_id=request.transaction_id,
                payment_id=cached_payment["payment_id"],
                amount=cached_payment["amount"],
                currency=cached_payment["currency"],
            ),
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

    # 5. Commit inventory
    from app.api.negotiate import inventory

    try:
        committed_hold = inventory.commit_hold(
            request.hold_token,
        )

    except InventoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": exc.code,
                "message": exc.message,
            },
        )

    # 6. Generate settlement receipt
    receipt_digest = _receipt_digest(
        transaction_id=request.transaction_id,
        payment_id=payment["payment_id"],
        amount=payment["amount"],
        currency=payment["currency"],
    )

    return SettlementResult(
        transaction_id=request.transaction_id,
        payment_id=payment["payment_id"],
        status="SETTLED",
        amount=payment["amount"],
        currency=payment["currency"],
        receipt_digest=receipt_digest,
    )