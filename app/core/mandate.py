import base64
import json
import time
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from app.models import Mandate

class MandateVerificationError(Exception):
    """
    Raised when a delegation mandate fails verification.

    The error contains a machine-readable error code so the API layer
    can return a deterministic response to the buyer agent.
    """

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def canonicalize_mandate(mandate: Mandate) -> bytes:
    """
    Create the exact byte representation that is expected to have
    been signed by the human.

    The signature itself is excluded from the signed payload.

    Canonicalization is critical:
    both the signer and verifier must sign/verify the exact same bytes.
    """

    payload = mandate.model_dump()

    # The signature cannot sign itself.
    payload.pop("signature", None)

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def decode_base64(value: str, field_name: str) -> bytes:
    """
    Decode a Base64-encoded field.

    Raises a protocol-specific error rather than leaking low-level
    decoding exceptions to the API layer.
    """

    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        raise MandateVerificationError(
            "INVALID_BASE64",
            f"{field_name} is not valid Base64.",
        )


def verify_signature(mandate: Mandate) -> None:
    """
    Verify the Ed25519 signature attached to the mandate.
    """

    public_key_bytes = decode_base64(
        mandate.public_key,
        "public_key",
    )

    signature_bytes = decode_base64(
        mandate.signature,
        "signature",
    )

    # An Ed25519 public key is exactly 32 bytes.
    if len(public_key_bytes) != 32:
        raise MandateVerificationError(
            "INVALID_PUBLIC_KEY",
            "Ed25519 public key must be 32 bytes.",
        )

    # An Ed25519 signature is exactly 64 bytes.
    if len(signature_bytes) != 64:
        raise MandateVerificationError(
            "INVALID_SIGNATURE",
            "Ed25519 signature must be 64 bytes.",
        )

    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            public_key_bytes
        )
        public_key.verify(
            signature_bytes,
            canonicalize_mandate(mandate),
        )

    except InvalidSignature:
        raise MandateVerificationError(
            "INVALID_SIGNATURE",
            "Mandate signature verification failed.",
        )


def verify_temporal_validity(
    mandate: Mandate,
    clock_skew_seconds: int = 30,
) -> None:
    """
    Verify that the mandate is currently valid.

    A small clock-skew allowance prevents otherwise valid requests
    from failing because the agent and merchant clocks differ slightly.
    """
    now = int(time.time())

    if mandate.issued_at > now + clock_skew_seconds:
        raise MandateVerificationError(
            "MANDATE_NOT_YET_VALID",
            "Mandate issued_at is in the future.",
        )

    if mandate.expires_at < now - clock_skew_seconds:
        raise MandateVerificationError(
            "MANDATE_EXPIRED",
            "Delegation mandate has expired.",
        )


def verify_authorization_scope(
    mandate: Mandate,
    *,
    merchant_id: str,
    category: str,
    amount: int,
    quantity: int,
) -> None:
    """
    Verify that the proposed transaction falls within the authority
    delegated by the human.
    """

    constraints = mandate.constraints

    # Merchant binding
    if mandate.merchant_id != merchant_id:
        raise MandateVerificationError(
            "MANDATE_MERCHANT_MISMATCH",
            "Mandate is not valid for this merchant.",
        )

    # Currency
    if constraints.currency != "INR":
        raise MandateVerificationError(
            "UNSUPPORTED_CURRENCY",
            "Mandate currency is not supported by this merchant.",
        )

    # Budget
    if amount > constraints.max_spend:
        raise MandateVerificationError(
            "BUDGET_EXCEEDED",
            (
                f"Transaction amount {amount} exceeds the "
                f"mandated maximum of {constraints.max_spend}."
            ),
        )

    # Quantity
    if quantity > constraints.max_quantity:
        raise MandateVerificationError(
            "QUANTITY_EXCEEDED",
            (
                f"Requested quantity {quantity} exceeds the "
                f"mandated maximum of {constraints.max_quantity}."
            ),
        )

    # Category
    if (
        constraints.allowed_categories
        and category not in constraints.allowed_categories
    ):
        raise MandateVerificationError(
            "CATEGORY_NOT_AUTHORIZED",
            f"Category '{category}' is not authorized by the mandate.",
        )


def verify_mandate(
    mandate: Mandate,
    *,
    merchant_id: str,
    category: str,
    amount: int,
    quantity: int,
    clock_skew_seconds: int = 30,
) -> None:
    """
    Complete mandate verification pipeline.

    Verification order is intentional:

        1. Temporal validity
        2. Cryptographic signature
        3. Authorization scope

    No settlement logic should execute before this function succeeds.
    """

    verify_temporal_validity(
        mandate,
        clock_skew_seconds=clock_skew_seconds,
    )

    verify_signature(mandate)
    
    verify_authorization_scope(
        mandate,
        merchant_id=merchant_id,
        category=category,
        amount=amount,
        quantity=quantity,
    )