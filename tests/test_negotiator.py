from app.services.negotiator import (
    BoundedNegotiator,
    NegotiationRequest,
)

negotiator = BoundedNegotiator()

def test_valid_negotiation_is_approved():
    request = NegotiationRequest(
        sku="LAPTOP-PRO-01",
        category="electronics",
        quantity=1,
        region="IN",
        requested_unit_price=4800,
    )
    result = negotiator.evaluate(request)

    assert result.approved is True
    assert result.approved_unit_price == 4800
    assert result.total_amount == 4800
    assert result.reason_code is None

def test_exact_floor_price_is_approved():
    request = NegotiationRequest(
        sku="LAPTOP-PRO-01",
        category="electronics",
        quantity=1,
        region="IN",
        requested_unit_price=4600,
    )
    result = negotiator.evaluate(request)

    assert result.approved is True
    assert result.approved_unit_price == 4600

def test_price_below_floor_is_rejected():
    request = NegotiationRequest(
        sku="LAPTOP-PRO-01",
        category="electronics",
        quantity=1,
        region="IN",
        requested_unit_price=4599,
    )
    result = negotiator.evaluate(request)

    assert result.approved is False
    assert result.reason_code == "RULE_MAX_DISCOUNT_EXCEEDED"
    assert result.approved_unit_price is None

def test_price_above_base_price_is_rejected():
    request = NegotiationRequest(
        sku="LAPTOP-PRO-01",
        category="electronics",
        quantity=1,
        region="IN",
        requested_unit_price=5001,
    )
    result = negotiator.evaluate(request)

    assert result.approved is False
    assert result.reason_code == "PRICE_ABOVE_BASE_PRICE"

def test_invalid_quantity_is_rejected():
    request = NegotiationRequest(
        sku="LAPTOP-PRO-01",
        category="electronics",
        quantity=100,
        region="IN",
        requested_unit_price=4800,
    )
    result = negotiator.evaluate(request)

    assert result.approved is False
    assert result.reason_code == "MAX_QUANTITY_EXCEEDED"

def test_invalid_region_is_rejected():
    request = NegotiationRequest(
        sku="LAPTOP-PRO-01",
        category="electronics",
        quantity=1,
        region="US",
        requested_unit_price=4800,
    )
    result = negotiator.evaluate(request)

    assert result.approved is False
    assert result.reason_code == "REGION_NOT_SUPPORTED"

def test_invalid_category_is_rejected():
    request = NegotiationRequest(
        sku="LAPTOP-PRO-01",
        category="food",
        quantity=1,
        region="IN",
        requested_unit_price=4800,
    )
    result = negotiator.evaluate(request)

    assert result.approved is False
    assert result.reason_code == "CATEGORY_MISMATCH"

def test_unknown_sku_is_rejected():
    request = NegotiationRequest(
        sku="UNKNOWN-001",
        category="electronics",
        quantity=1,
        region="IN",
        requested_unit_price=100,
    )
    result = negotiator.evaluate(request)

    assert result.approved is False
    assert result.reason_code == "SKU_NOT_FOUND"

def test_total_amount_is_calculated_from_approved_price():
    request = NegotiationRequest(
        sku="PHONE-01",
        category="electronics",
        quantity=3,
        region="IN",
        requested_unit_price=2850,
    )
    result = negotiator.evaluate(request)

    assert result.approved is True
    assert result.total_amount == 8550