from dataclasses import dataclass
from app.core.policy import (
    PolicyViolationError,
    ProductPolicy,
    calculate_floor_price,
    validate_proposal,
)

@dataclass(frozen=True)
class NegotiationRequest:
    """
    Parameters supplied by the buyer agent during negotiation.
    """
    sku: str
    category: str
    quantity: int
    region: str
    requested_unit_price: int

@dataclass(frozen=True)
class NegotiationResult:
    """
    Deterministic result of a negotiation attempt.

    `approved` indicates whether the requested terms satisfy
    merchant policy.
    """
    approved: bool
    sku: str
    requested_unit_price: int
    approved_unit_price: int | None
    quantity: int
    total_amount: int | None
    floor_price: int
    reason_code: str | None
    reason: str | None

class BoundedNegotiator:
    """
    Deterministic negotiation engine.

    This component does NOT negotiate by itself using an LLM.

    It establishes the hard boundary that any future LLM-based
    negotiator must pass through.
    """

    def evaluate(
        self,
        request: NegotiationRequest,
    ) -> NegotiationResult:
        """
        Evaluate one proposed set of commercial terms.

        The merchant policy remains authoritative.
        """
        try:
            product = validate_proposal(
                sku=request.sku,
                category=request.category,
                quantity=request.quantity,
                region=request.region,
                requested_unit_price=request.requested_unit_price,
            )

        except PolicyViolationError as exc:
            floor_price = self._get_floor_price(
                request.sku,
            )
            return NegotiationResult(
                approved=False,
                sku=request.sku,
                requested_unit_price=request.requested_unit_price,
                approved_unit_price=None,
                quantity=request.quantity,
                total_amount=None,
                floor_price=floor_price,
                reason_code=exc.code,
                reason=exc.message,
            )

        total_amount = (
            request.requested_unit_price
            * request.quantity
        )

        floor_price = calculate_floor_price(
            product.base_price,
            product.max_discount_percent,
        )

        return NegotiationResult(
            approved=True,
            sku=product.sku,
            requested_unit_price=request.requested_unit_price,
            approved_unit_price=request.requested_unit_price,
            quantity=request.quantity,
            total_amount=total_amount,
            floor_price=floor_price,
            reason_code=None,
            reason=None,
        )

    @staticmethod
    def _get_floor_price(sku: str) -> int:
        """
        Retrieve the merchant floor price for a SKU.

        Unknown SKUs return zero here because the actual policy
        validation error remains the authoritative rejection reason.
        """
        from app.core.policy import PRODUCT_CATALOG

        product = PRODUCT_CATALOG.get(sku)
        if product is None:
            return 0

        return calculate_floor_price(
            product.base_price,
            product.max_discount_percent,
        )

negotiator = BoundedNegotiator()