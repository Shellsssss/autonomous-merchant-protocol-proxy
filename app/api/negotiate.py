import time
from fastapi import APIRouter, HTTPException, status
from app.config import get_settings
from app.core.inventory import (
    InMemoryInventory,
    InventoryError,
)
from app.core.mandate import (
    MandateVerificationError,
    verify_mandate,
)
from app.core.policy import (
    PolicyViolationError,
    # validate_proposal,
    get_product_policy,
)
from app.services.negotiator import (
    NegotiationRequest,
    negotiator,
)
from app.models import Deal, PurchaseProposal
from app.services.deal_store import deal_store
from app.core.transaction import TransactionState
from app.core.transaction_store import (
    TransactionConflictError,
    transaction_store,
)
from app.models.transaction import Transaction

router = APIRouter(
    prefix="/api/v1/agent",
    tags=["Agent Commerce"],
)

# Demo inventory
inventory = InMemoryInventory(
    initial_inventory={
        "LAPTOP-PRO-01": 10,
        "PHONE-PRO-01": 20,
        "HEADPHONES-01": 50,
    },
    hold_ttl_seconds=60,
)

@router.post(
    "/negotiate",
    response_model=Deal,
    status_code=status.HTTP_200_OK,
)
async def negotiate(proposal: PurchaseProposal) -> Deal:
    """
    Validate an autonomous buyer's purchase proposal, create a transaction,
    and place a temporary inventory hold.

    Security boundary:

        Agent proposal
              ↓
        Mandate verification
              ↓
        Merchant policy
              ↓
        Transaction VALIDATED
              ↓
        Inventory hold
              ↓
        Transaction HELD
              ↓
          Approved Deal

    No LLM or payment provider is called here.
    """
    settings = get_settings()
    timestamp = int(time.time())

    # 1. Merchant binding
    if proposal.merchant_id != settings.merchant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "MERCHANT_MISMATCH",
                "message": "Proposal is addressed to a different merchant.",
            },
        )

    # 2. Calculate requested quantity
    total_quantity = sum(item.quantity for item in proposal.items)

    # 3. Calculate proposed transaction amount
    requested_amount = proposal.requested_unit_price * total_quantity

    # 4. Create transaction record
    transaction = Transaction(
        transaction_id=proposal.transaction_id,
        merchant_id=settings.merchant_id,
        created_at=timestamp,
        updated_at=timestamp,
    )

    try:
        transaction_store.create(transaction)
    except TransactionConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "TRANSACTION_CONFLICT",
                "message": str(exc),
            },
        )

    # 5. Verify human delegation
    try:
        verify_mandate(
            proposal.mandate,
            merchant_id=settings.merchant_id,
            category=proposal.category,
            amount=requested_amount,
            quantity=total_quantity,
            clock_skew_seconds=settings.clock_skew_seconds,
        )

    except MandateVerificationError as exc:
        transaction_store.update_state(
            proposal.transaction_id,
            TransactionState.FAILED,
            timestamp=int(time.time()),
            reason=exc.code,
        )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": exc.code,
                "message": exc.message,
            },
        )

    # 6. Evaluate merchant invariants through the bounded negotiator.
    # The negotiator is deterministic and does not trust any
    # LLM-generated pricing decision.
    negotiation_request = NegotiationRequest(
        sku=proposal.items[0].sku,
        category=proposal.category,
        quantity=total_quantity,
        region=proposal.region,
        requested_unit_price=proposal.requested_unit_price,
    )
    negotiation_result = negotiator.evaluate(negotiation_request)

    if not negotiation_result.approved:
        transaction_store.update_state(
            proposal.transaction_id,
            TransactionState.FAILED,
            timestamp=int(time.time()),
            reason=negotiation_result.reason_code,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": negotiation_result.reason_code,
                "message": negotiation_result.reason,
            },
        )

    # 7. Transaction has passed the deterministic trust boundary
    transaction_store.update_state(
        proposal.transaction_id,
        TransactionState.VALIDATED,
        timestamp=int(time.time()),
        reason="Mandate and merchant policy validation succeeded.",
    )
    product = get_product_policy(proposal.items[0].sku)

    # 8. Create atomic inventory hold
    try:
        hold = inventory.create_hold(
            transaction_id=proposal.transaction_id,
            sku=product.sku,
            quantity=total_quantity,
        )
    except InventoryError as exc:
        transaction_store.update_state(
            proposal.transaction_id,
            TransactionState.FAILED,
            timestamp=int(time.time()),
            reason=exc.code,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": exc.code,
                "message": exc.message,
            },
        )

    # 9. Transaction now owns an active inventory hold
    transaction = transaction_store.get(proposal.transaction_id)
    transaction_store.update(
        transaction.model_copy(
            update={
                "hold_token": hold.hold_token,
                "updated_at": int(time.time()),
            }
        )
    )

    transaction_store.update_state(
        proposal.transaction_id,
        TransactionState.HELD,
        timestamp=int(time.time()),
        reason="Inventory successfully reserved.",
        metadata={
            "hold_token": hold.hold_token,
            "expires_at": hold.expires_at,
        },
    )

    # 10. Calculate approved deal
    approved_unit_price = proposal.requested_unit_price
    total_amount = approved_unit_price * total_quantity

    # 11. Create the server-trusted deal
    deal = Deal(
        transaction_id=proposal.transaction_id,
        merchant_id=settings.merchant_id,
        sku=product.sku,
        quantity=total_quantity,
        base_unit_price=product.base_price,
        approved_unit_price=approved_unit_price,
        total_amount=total_amount,
        currency=settings.currency,
        hold_token=hold.hold_token,
        expires_at=hold.expires_at,
        state=hold.state,
    )

    # 12. Persist the deal. If this fails, release the inventory
    # reservation and mark the transaction as failed.
    try:
        deal_store.create(deal)
    except Exception as exc:
        try:
            inventory.release_hold(hold.hold_token)
        finally:
            transaction_store.update_state(
                proposal.transaction_id,
                TransactionState.FAILED,
                timestamp=int(time.time()),
                reason="Deal creation failed after inventory hold.",
                metadata={"error": str(exc)},
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "DEAL_CREATION_FAILED",
                "message": "Unable to create the deal.",
            },
        )

    # 13. Attach the deal ID to the transaction.
    # The current Deal model uses transaction_id as its identifier,
    # so the transaction itself is the deal reference.
    transaction = transaction_store.get(proposal.transaction_id)
    transaction_store.update(
        transaction.model_copy(
            update={
                "deal_id": proposal.transaction_id,
                "updated_at": int(time.time()),
            }
        )
    )
    return deal