import pytest
import hashlib
import hmac
from unittest.mock import Mock, patch
from app.services.razorpay_adapter import (
    RazorpayAdapter,
    RazorpayError,
)

def make_adapter() -> RazorpayAdapter:
    adapter = RazorpayAdapter()
    adapter.key_id = "rzp_test_fake"
    adapter.key_secret = "fake_secret"
    return adapter

def test_create_order_converts_rupees_to_paise():
    adapter = make_adapter()
    fake_response = Mock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "id": "order_test_001",
        "amount": 480000,
        "currency": "INR",
        "status": "created",
    }

    with patch(
        "app.services.razorpay_adapter.requests.post",
        return_value=fake_response,
    ) as mock_post:
        order = adapter.create_order(
            transaction_id="txn_test_001",
            amount=4800,
            currency="INR",
        )

    assert order.order_id == "order_test_001"
    assert order.amount == 4800
    assert order.currency == "INR"
    assert order.status == "created"

    _, kwargs = mock_post.call_args

    assert kwargs["json"]["amount"] == 480000
    assert kwargs["json"]["currency"] == "INR"
    assert kwargs["json"]["receipt"] == "txn_test_001"

def test_zero_amount_is_rejected():
    adapter = make_adapter()
    with pytest.raises(RazorpayError) as exc_info:
        adapter.create_order(
            transaction_id="txn_test_001",
            amount=0,
            currency="INR",
        )
    assert exc_info.value.code == "INVALID_AMOUNT"

def test_negative_amount_is_rejected():
    adapter = make_adapter()
    with pytest.raises(RazorpayError) as exc_info:
        adapter.create_order(
            transaction_id="txn_test_001",
            amount=-100,
            currency="INR",
        )
    assert exc_info.value.code == "INVALID_AMOUNT"

def test_missing_credentials_are_rejected():
    adapter = RazorpayAdapter()
    adapter.key_id = None
    adapter.key_secret = None

    with pytest.raises(RazorpayError) as exc_info:
        adapter.create_order(
            transaction_id="txn_test_001",
            amount=4800,
            currency="INR",
        )

    assert exc_info.value.code == (
        "RAZORPAY_NOT_CONFIGURED"
    )

def test_razorpay_http_error_is_converted():
    adapter = make_adapter()
    fake_response = Mock()
    fake_response.status_code = 400

    with patch(
        "app.services.razorpay_adapter.requests.post",
        return_value=fake_response,
    ):
        with pytest.raises(RazorpayError) as exc_info:
            adapter.create_order(
                transaction_id="txn_test_001",
                amount=4800,
                currency="INR",
            )

    assert exc_info.value.code == (
        "RAZORPAY_ORDER_CREATION_FAILED"
    )

def test_razorpay_invalid_json_is_rejected():
    adapter = make_adapter()
    fake_response = Mock()
    fake_response.status_code = 200
    fake_response.json.side_effect = ValueError()

    with patch(
        "app.services.razorpay_adapter.requests.post",
        return_value=fake_response,
    ):
        with pytest.raises(RazorpayError) as exc_info:
            adapter.create_order(
                transaction_id="txn_test_001",
                amount=4800,
                currency="INR",
            )

    assert exc_info.value.code == (
        "RAZORPAY_INVALID_RESPONSE"
    )

def test_razorpay_response_without_order_id_is_rejected():
    adapter = make_adapter()
    fake_response = Mock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "amount": 480000,
        "currency": "INR",
        "status": "created",
    }

    with patch(
        "app.services.razorpay_adapter.requests.post",
        return_value=fake_response,
    ):
        with pytest.raises(RazorpayError) as exc_info:
            adapter.create_order(
                transaction_id="txn_test_001",
                amount=4800,
                currency="INR",
            )

    assert exc_info.value.code == (
        "RAZORPAY_INVALID_RESPONSE"
    )

def test_payment_signature_verification():
    adapter = RazorpayAdapter.__new__(RazorpayAdapter)
    adapter.key_secret = "test_secret"

    order_id = "order_test_123"
    payment_id = "pay_test_123"

    signature = hmac.new(
        b"test_secret",
        f"{order_id}|{payment_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    assert adapter.verify_payment_signature(
        order_id=order_id,
        payment_id=payment_id,
        signature=signature,
    )

def test_invalid_payment_signature_is_rejected():
    adapter = RazorpayAdapter.__new__(RazorpayAdapter)
    adapter.key_secret = "test_secret"
    assert not adapter.verify_payment_signature(
        order_id="order_test_123",
        payment_id="pay_test_123",
        signature="invalid_signature",
    )