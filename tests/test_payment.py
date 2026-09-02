import pytest
from app.services.payment import (
    PaymentError,
    TestPaymentProvider,
)

def test_payment_capture_succeeds():
    provider = TestPaymentProvider()
    result = provider.capture(
        transaction_id="txn_test_001",
        amount=4800,
        currency="INR",
    )

    assert result.status == "CAPTURED"
    assert result.amount == 4800
    assert result.currency == "INR"
    assert result.payment_id.startswith("pay_test_")
    assert len(result.receipt_digest) == 64

def test_payment_amount_must_be_positive():
    provider = TestPaymentProvider()
    with pytest.raises(PaymentError) as exc:
        provider.capture(
            transaction_id="txn_test_001",
            amount=0,
            currency="INR",
        )
    assert exc.value.code == "INVALID_PAYMENT_AMOUNT"

def test_payment_currency_is_required():
    provider = TestPaymentProvider()
    with pytest.raises(PaymentError) as exc:
        provider.capture(
            transaction_id="txn_test_001",
            amount=4800,
            currency="",
        )
    assert exc.value.code == "INVALID_CURRENCY"

def test_receipt_digest_is_generated():
    provider = TestPaymentProvider()
    result = provider.capture(
        transaction_id="txn_test_001",
        amount=4800,
        currency="INR",
    )
    assert result.receipt_digest
    assert len(result.receipt_digest) == 64