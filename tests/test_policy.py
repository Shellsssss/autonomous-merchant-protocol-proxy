import pytest
from app.core.policy import (
    PolicyViolationError,
    calculate_floor_price,
    validate_proposal,
)

SKU = "LAPTOP-PRO-01"

def test_floor_price_is_calculated_correctly():
    floor = calculate_floor_price(
        base_price=5000,
        max_discount_percent=8,
    )

    assert floor == 4600

def test_valid_proposal_is_accepted():
    product = validate_proposal(
        sku=SKU,
        category="electronics",
        quantity=1,
        region="IN",
        requested_unit_price=4800,
    )
    assert product.sku == SKU

def test_price_below_floor_is_rejected():
    with pytest.raises(PolicyViolationError) as exc:
        validate_proposal(
            sku=SKU,
            category="electronics",
            quantity=1,
            region="IN",
            requested_unit_price=4599,
        )
    assert exc.value.code == "RULE_MAX_DISCOUNT_EXCEEDED"

def test_adversarial_extreme_discount_is_rejected():
    with pytest.raises(PolicyViolationError) as exc:
        validate_proposal(
            sku=SKU,
            category="electronics",
            quantity=1,
            region="IN",
            requested_unit_price=10,
        )
    assert exc.value.code == "RULE_MAX_DISCOUNT_EXCEEDED"

def test_price_above_base_price_is_rejected():
    with pytest.raises(PolicyViolationError) as exc:
        validate_proposal(
            sku=SKU,
            category="electronics",
            quantity=1,
            region="IN",
            requested_unit_price=5500,
        )
    assert exc.value.code == "PRICE_ABOVE_BASE_PRICE"

def test_unknown_sku_is_rejected():
    with pytest.raises(PolicyViolationError) as exc:
        validate_proposal(
            sku="UNKNOWN-SKU",
            category="electronics",
            quantity=1,
            region="IN",
            requested_unit_price=1000,
        )
    assert exc.value.code == "SKU_NOT_FOUND"

def test_wrong_category_is_rejected():
    with pytest.raises(PolicyViolationError) as exc:
        validate_proposal(
            sku=SKU,
            category="fashion",
            quantity=1,
            region="IN",
            requested_unit_price=4800,
        )
    assert exc.value.code == "CATEGORY_MISMATCH"

def test_quantity_above_limit_is_rejected():
    with pytest.raises(PolicyViolationError) as exc:
        validate_proposal(
            sku=SKU,
            category="electronics",
            quantity=6,
            region="IN",
            requested_unit_price=4800,
        )
    assert exc.value.code == "MAX_QUANTITY_EXCEEDED"

def test_unsupported_region_is_rejected():
    with pytest.raises(PolicyViolationError) as exc:
        validate_proposal(
            sku=SKU,
            category="electronics",
            quantity=1,
            region="US",
            requested_unit_price=4800,
        )
    assert exc.value.code == "REGION_NOT_SUPPORTED"