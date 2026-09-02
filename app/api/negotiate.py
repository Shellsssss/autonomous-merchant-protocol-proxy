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
    Validate an autonomous buyer's purchase proposal and place a
    temporary inventory hold.

    Security boundary:

        Agent proposal
              ↓
        Mandate verification
              ↓
        Merchant policy
              ↓
        Inventory hold
              ↓
          Approved Deal

    No LLM or payment provider is called here.
    """
    settings = get_settings()

    # 1. Merchant binding
    if proposal.merchant_id != settings.merchant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "MERCHANT_MISMATCH",
                "message": (
                    "Proposal is addressed to a different merchant."
                ),
            },
        )

    # 2. Calculate requested quantity
    total_quantity = sum(
        item.quantity
        for item in proposal.items
    )

    # 3. Calculate proposed transaction amount
    requested_amount = (
        proposal.requested_unit_price * total_quantity
    )

    # 4. Verify human delegation
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": exc.code,
                "message": exc.message,
            },
        )

    # 5. Evaluate merchant invariants through the bounded negotiator.
    # The negotiator is deterministic and does not trust any
    # LLM-generated pricing decision.
    negotiation_request = NegotiationRequest(
        sku=proposal.items[0].sku,
        category=proposal.category,
        quantity=total_quantity,
        region=proposal.region,
        requested_unit_price=proposal.requested_unit_price,
    )

    negotiation_result = negotiator.evaluate(
        negotiation_request,
    )

    if not negotiation_result.approved:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": negotiation_result.reason_code,
                "message": negotiation_result.reason,
            },
        )

    product = get_product_policy(
        proposal.items[0].sku
    )

    # 6. Create atomic inventory hold
    try:
        hold = inventory.create_hold(
            transaction_id=proposal.transaction_id,
            sku=product.sku,
            quantity=total_quantity,
        )

    except InventoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": exc.code,
                "message": exc.message,
            },
        )

    # 7. Calculate approved deal
    approved_unit_price = proposal.requested_unit_price
    total_amount = (
        approved_unit_price * total_quantity
    )

    # 8. Return held deal
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
    deal_store.create(deal)

    return deal