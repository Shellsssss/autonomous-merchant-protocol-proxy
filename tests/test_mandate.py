import base64
import time
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from app.core.mandate import (
    MandateVerificationError,
    canonicalize_mandate,
    verify_mandate,
)
from app.models import Mandate, SpendingConstraints

MERCHANT_ID = "merchant_demo_01"

def create_signed_mandate(
    *,
    max_spend: int = 5000,
    category: str = "electronics",
    max_quantity: int = 2,
    expires_in: int = 300,
    merchant_id: str = MERCHANT_ID,
):
    """
    Test helper that creates a real Ed25519 keypair and signs a mandate.

    This exists only inside the test suite.
    """

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    now = int(time.time())

    # For an expired test mandate, create a mandate that was valid
    # when issued but has already passed its expiry time.
    if expires_in < 0:
        issued_at = now + expires_in - 300
        expires_at = now + expires_in
    else:
        issued_at = now
        expires_at = now + expires_in

    mandate = Mandate(
        mandate_id="mnd_test_001",
        subject="buyer_agent_test",
        merchant_id=merchant_id,
        constraints=SpendingConstraints(
            max_spend=max_spend,
            currency="INR",
            allowed_categories=[category],
            max_quantity=max_quantity,
        ),
        issued_at=issued_at,
        expires_at=expires_at,
        nonce="test_nonce_123456789",
        public_key=base64.b64encode(
            public_key.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode(),
        signature="placeholder",
    )

    signature = private_key.sign(
        canonicalize_mandate(mandate)
    )

    mandate.signature = base64.b64encode(signature).decode()
    return mandate

# Valid mandate
def test_valid_mandate_is_accepted():
    mandate = create_signed_mandate()

    verify_mandate(
        mandate,
        merchant_id=MERCHANT_ID,
        category="electronics",
        amount=4500,
        quantity=1,
    )

# Signature verification
def test_modified_mandate_is_rejected():
    mandate = create_signed_mandate()

    # Change the spending authority AFTER the signature was generated.
    mandate.constraints.max_spend = 50000

    with pytest.raises(MandateVerificationError) as exc:
        verify_mandate(
            mandate,
            merchant_id=MERCHANT_ID,
            category="electronics",
            amount=10000,
            quantity=1,
        )

    assert exc.value.code == "INVALID_SIGNATURE"

# Expiry
def test_expired_mandate_is_rejected():
    mandate = create_signed_mandate(expires_in=-300)

    with pytest.raises(MandateVerificationError) as exc:
        verify_mandate(
            mandate,
            merchant_id=MERCHANT_ID,
            category="electronics",
            amount=1000,
            quantity=1,
        )

    assert exc.value.code == "MANDATE_EXPIRED"

# Merchant binding
def test_wrong_merchant_is_rejected():
    mandate = create_signed_mandate()

    with pytest.raises(MandateVerificationError) as exc:
        verify_mandate(
            mandate,
            merchant_id="another_merchant",
            category="electronics",
            amount=1000,
            quantity=1,
        )

    assert exc.value.code == "MANDATE_MERCHANT_MISMATCH"

# Budget
def test_budget_exceeded_is_rejected():
    mandate = create_signed_mandate(max_spend=5000)

    with pytest.raises(MandateVerificationError) as exc:
        verify_mandate(
            mandate,
            merchant_id=MERCHANT_ID,
            category="electronics",
            amount=5001,
            quantity=1,
        )

    assert exc.value.code == "BUDGET_EXCEEDED"

# Category
def test_unauthorized_category_is_rejected():
    mandate = create_signed_mandate(
        category="electronics"
    )

    with pytest.raises(MandateVerificationError) as exc:
        verify_mandate(
            mandate,
            merchant_id=MERCHANT_ID,
            category="fashion",
            amount=1000,
            quantity=1,
        )

    assert exc.value.code == "CATEGORY_NOT_AUTHORIZED"

# Quantity
def test_quantity_exceeded_is_rejected():
    mandate = create_signed_mandate(
        max_quantity=2
    )

    with pytest.raises(MandateVerificationError) as exc:
        verify_mandate(
            mandate,
            merchant_id=MERCHANT_ID,
            category="electronics",
            amount=2000,
            quantity=3,
        )

    assert exc.value.code == "QUANTITY_EXCEEDED"