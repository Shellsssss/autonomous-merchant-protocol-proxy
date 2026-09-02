import hashlib
import hmac
import requests
from dataclasses import dataclass
from app.config import get_settings

class RazorpayError(Exception):
    """
    Base exception for Razorpay integration failures.
    """
    def __init__(
        self,
        code: str,
        message: str,
    ):
        self.code = code
        self.message = message
        super().__init__(message)

@dataclass(frozen=True)
class RazorpayOrder:
    """
    Minimal representation of a Razorpay order required by AMPP.
    """
    order_id: str
    amount: int
    currency: str
    status: str

class RazorpayAdapter:
    """
    Thin adapter around the Razorpay Orders API.

    Important:
        This class is responsible only for communicating with
        Razorpay.

        It does NOT decide whether a transaction is authorized.
        Mandates, merchant policy, inventory, and idempotency are
        handled elsewhere.
    """
    BASE_URL = "https://api.razorpay.com/v1"

    def __init__(self):
        settings = get_settings()
        self.key_id = settings.razorpay_key_id
        self.key_secret = settings.razorpay_key_secret

    def create_order(
        self,
        *,
        transaction_id: str,
        amount: int,
        currency: str,
    ) -> RazorpayOrder:
        """
        Create a Razorpay Test Mode order.

        Razorpay expects the amount in the smallest currency unit.

        For INR:
            ₹4,800 -> 480000 paise
        """
        if amount <= 0:
            raise RazorpayError(
                "INVALID_AMOUNT",
                "Order amount must be greater than zero.",
            )

        # if not self.key_id or not self.key_secret:
        #     return RazorpayOrder(
        #         order_id=f"order_test_{transaction_id}",
        #         amount=amount,
        #         currency=currency,
        #         status="created",
        #     )
        if not self.key_id or not self.key_secret:
            raise RazorpayError(
                "RAZORPAY_NOT_CONFIGURED",
                "Razorpay credentials are not configured.",
            )

        payload = {
            "amount": amount * 100,
            "currency": currency,
            "receipt": transaction_id,
            "notes": {
                "ampp_transaction_id": transaction_id,
            },
        }

        try:
            response = requests.post(
                f"{self.BASE_URL}/orders",
                json=payload,
                auth=(
                    self.key_id,
                    self.key_secret,
                ),
                timeout=10,
            )
        except requests.RequestException as exc:
            raise RazorpayError(
                "RAZORPAY_NETWORK_ERROR",
                "Unable to reach Razorpay.",
            ) from exc

        if response.status_code >= 400:
            raise RazorpayError(
                "RAZORPAY_ORDER_CREATION_FAILED",
                (
                    f"Razorpay rejected order creation "
                    f"with HTTP {response.status_code}."
                ),
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise RazorpayError(
                "RAZORPAY_INVALID_RESPONSE",
                "Razorpay returned invalid JSON.",
            ) from exc

        order_id = data.get("id")

        if not order_id:
            raise RazorpayError(
                "RAZORPAY_INVALID_RESPONSE",
                "Razorpay response did not contain an order ID.",
            )

        return RazorpayOrder(
            order_id=order_id,
            amount=amount,
            currency=currency,
            status=data.get(
                "status",
                "created",
            ),
        )

    def verify_payment_signature(
        self,
        *,
        order_id: str,
        payment_id: str,
        signature: str,
    ) -> bool:
        """
        Verify the Razorpay payment signature locally.

        Razorpay signs:
            order_id|payment_id

        using the Razorpay key secret and HMAC-SHA256.
        """
        if not self.key_secret:
            raise RazorpayError(
                "RAZORPAY_NOT_CONFIGURED",
                "Razorpay credentials are not configured.",
            )

        message = f"{order_id}|{payment_id}".encode("utf-8")
        expected_signature = hmac.new(
            self.key_secret.encode("utf-8"),
            message,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(
            expected_signature,
            signature,
        )

razorpay_adapter = RazorpayAdapter()