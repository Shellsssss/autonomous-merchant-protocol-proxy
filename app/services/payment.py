import hashlib
import uuid
from dataclasses import dataclass

class PaymentError(Exception):
    """
    Base exception for payment-related failures.
    """
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

@dataclass(frozen=True)
class PaymentResult:
    """
    Result returned by the payment rail.
    """
    payment_id: str
    status: str
    amount: int
    currency: str
    receipt_digest: str

class TestPaymentProvider:
    """
    Deterministic in-process payment provider for the AMPP prototype.

    This represents the boundary where a real Razorpay/x402
    integration will eventually be connected.

    The settlement layer should not need to know how the payment
    provider actually processes a payment.
    """

    def capture(
        self,
        *,
        transaction_id: str,
        amount: int,
        currency: str,
    ) -> PaymentResult:
        """
        Capture a payment for the requested transaction.

        The prototype always succeeds for valid positive amounts.
        """
        if amount <= 0:
            raise PaymentError(
                "INVALID_PAYMENT_AMOUNT",
                "Payment amount must be greater than zero.",
            )

        if not currency:
            raise PaymentError(
                "INVALID_CURRENCY",
                "Payment currency is required.",
            )

        payment_id = (
            f"pay_test_{uuid.uuid4().hex[:16]}"
        )

        receipt_payload = (
            f"{transaction_id}|"
            f"{payment_id}|"
            f"{amount}|"
            f"{currency}"
        )

        receipt_digest = hashlib.sha256(
            receipt_payload.encode()
        ).hexdigest()

        return PaymentResult(
            payment_id=payment_id,
            status="CAPTURED",
            amount=amount,
            currency=currency,
            receipt_digest=receipt_digest,
        )

payment_provider = TestPaymentProvider()