from dataclasses import dataclass

class PolicyViolationError(Exception):
    """
    Raised when a proposed transaction violates a merchant invariant.

    `code` is intended to be machine-readable so the buyer agent
    and Mission Control dashboard can understand exactly why a
    transaction was rejected.
    """

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

@dataclass(frozen=True)
class ProductPolicy:
    """
    Deterministic rules associated with one merchant SKU.
    """
    sku: str
    name: str
    category: str
    base_price: int
    max_discount_percent: int
    min_quantity: int
    max_quantity: int
    allowed_regions: tuple[str, ...]

# Demo merchant catalog
PRODUCT_CATALOG: dict[str, ProductPolicy] = {
    "LAPTOP-PRO-01": ProductPolicy(
        sku="LAPTOP-PRO-01",
        name="AMPP Pro Laptop",
        category="electronics",
        base_price=5000,
        max_discount_percent=8,
        min_quantity=1,
        max_quantity=5,
        allowed_regions=("IN",),
    ),
    "PHONE-01": ProductPolicy(
        sku="PHONE-01",
        name="AMPP Smart Phone",
        category="electronics",
        base_price=3000,
        max_discount_percent=5,
        min_quantity=1,
        max_quantity=10,
        allowed_regions=("IN",),
    ),
    "HEADPHONES-01": ProductPolicy(
        sku="HEADPHONES-01",
        name="AMPP Wireless Headphones",
        category="electronics",
        base_price=1500,
        max_discount_percent=10,
        min_quantity=1,
        max_quantity=20,
        allowed_regions=("IN",),
    ),
}

def get_product_policy(sku: str) -> ProductPolicy:
    """
    Retrieve the immutable merchant policy for a SKU.
    """
    product = PRODUCT_CATALOG.get(sku)

    if product is None:
        raise PolicyViolationError(
            "SKU_NOT_FOUND",
            f"SKU '{sku}' does not exist in the merchant catalog.",
        )

    return product


def calculate_floor_price(
    base_price: int,
    max_discount_percent: int,
) -> int:
    """
    Calculate the minimum price the merchant is willing to accept.

    Example:

        base price = ₹5,000
        max discount = 8%

        floor = ₹5,000 × (1 - 0.08)
              = ₹4,600
    """

    discount = base_price * max_discount_percent // 100
    return base_price - discount


def validate_quantity(
    product: ProductPolicy,
    quantity: int,
) -> None:
    """
    Validate the requested quantity against merchant rules.
    """

    if quantity < product.min_quantity:
        raise PolicyViolationError(
            "MIN_QUANTITY_NOT_MET",
            (
                f"Quantity {quantity} is below the minimum "
                f"quantity of {product.min_quantity}."
            ),
        )

    if quantity > product.max_quantity:
        raise PolicyViolationError(
            "MAX_QUANTITY_EXCEEDED",
            (
                f"Quantity {quantity} exceeds the merchant "
                f"maximum of {product.max_quantity}."
            ),
        )


def validate_region(
    product: ProductPolicy,
    region: str,
) -> None:
    """
    Ensure the merchant is able to fulfill the order in the
    requested region.
    """

    if region not in product.allowed_regions:
        raise PolicyViolationError(
            "REGION_NOT_SUPPORTED",
            (
                f"Region '{region}' is not supported for "
                f"SKU '{product.sku}'."
            ),
        )


def validate_category(
    product: ProductPolicy,
    category: str,
) -> None:
    """
    Ensure the proposal category matches the merchant catalog.
    """

    if category != product.category:
        raise PolicyViolationError(
            "CATEGORY_MISMATCH",
            (
                f"Proposal category '{category}' does not match "
                f"merchant category '{product.category}'."
            ),
        )


def validate_price(
    product: ProductPolicy,
    requested_unit_price: int,
) -> int:
    """
    Validate the proposed unit price.

    Returns the approved price if valid.

    The important security property is that the requested price
    is never allowed below the merchant-defined floor.
    """

    floor_price = calculate_floor_price(
        product.base_price,
        product.max_discount_percent,
    )

    if requested_unit_price < floor_price:
        raise PolicyViolationError(
            "RULE_MAX_DISCOUNT_EXCEEDED",
            (
                f"Requested price ₹{requested_unit_price} is below "
                f"the merchant floor price of ₹{floor_price}."
            ),
        )

    if requested_unit_price > product.base_price:
        raise PolicyViolationError(
            "PRICE_ABOVE_BASE_PRICE",
            (
                f"Requested price ₹{requested_unit_price} exceeds "
                f"the base price of ₹{product.base_price}."
            ),
        )

    return requested_unit_price


def validate_proposal(
    *,
    sku: str,
    category: str,
    quantity: int,
    region: str,
    requested_unit_price: int,
) -> ProductPolicy:
    """
    Execute the complete deterministic merchant policy.

    This function must remain independent of any LLM.

    The result is either:

        ProductPolicy

    or:

        PolicyViolationError
    """
    product = get_product_policy(sku)

    validate_category(
        product,
        category,
    )

    validate_quantity(
        product,
        quantity,
    )

    validate_region(
        product,
        region,
    )

    validate_price(
        product,
        requested_unit_price,
    )

    return product