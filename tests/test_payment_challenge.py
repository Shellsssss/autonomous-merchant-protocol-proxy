import base64
import time
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from app.api.negotiate import inventory
from app.core.mandate import canonicalize_mandate
from app.core.transaction import TransactionState
from app.core.transaction_store import transaction_store
from app.main import app
from app.models import Mandate, SpendingConstraints
from app.services.deal_store import deal_store

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_state():
    inventory._inventory["LAPTOP-PRO-01"].available_quantity = 10
    inventory._inventory["PHONE-PRO-01"].available_quantity = 20
    inventory._inventory["HEADPHONES-01"].available_quantity = 50
    inventory._holds.clear()
    deal_store.clear()
    transaction_store.clear()

def create_signed_mandate(
    *,
    max_spend: int = 5000,
    category: str = "electronics",
    max_quantity: int = 2,
):
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    now = int(time.time())

    mandate = Mandate(
        mandate_id="mnd_payment_test_001",
        subject="buyer_agent_payment_test",
        merchant_id="merchant_demo_01",
        constraints=SpendingConstraints(
            max_spend=max_spend,
            currency="INR",
            allowed_categories=[category],
            max_quantity=max_quantity,
        ),
        issued_at=now,
        expires_at=now + 300,
        nonce="payment_test_nonce_123456",
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

    mandate.signature = base64.b64encode(
        signature
    ).decode()

    return mandate.model_dump()

def make_proposal(
    *,
    transaction_id: str = "txn_payment_test_001",
    price: int = 4800,
    category: str = "electronics",
    quantity: int = 1,
    max_spend: int = 5000,
):
    return {
        "transaction_id": transaction_id,
        "merchant_id": "merchant_demo_01",
        "items": [
            {
                "sku": "LAPTOP-PRO-01",
                "quantity": quantity,
            }
        ],
        "requested_unit_price": price,
        "category": category,
        "region": "IN",
        "mandate": create_signed_mandate(
            max_spend=max_spend,
            category=category,
            max_quantity=quantity,
        ),
    }

def create_held_transaction(
    transaction_id: str = "txn_payment_test_001",
):
    proposal = make_proposal(
        transaction_id=transaction_id,
    )
    response = client.post(
        "/api/v1/agent/negotiate",
        json=proposal,
    )
    assert response.status_code == 200
    return proposal, response.json()

def test_payment_challenge_returns_402():
    proposal, deal = create_held_transaction()
    response = client.get(
        f"/api/v1/agent/transactions/{proposal['transaction_id']}/payment"
    )
    assert response.status_code == 402

    data = response.json()
    assert data["protocol"] == "x402"
    assert data["version"] == "1"
    assert data["payment_required"] is True
    assert data["amount"] == deal["total_amount"]
    assert data["currency"] == deal["currency"]
    assert data["transaction_id"] == proposal["transaction_id"]
    assert data["hold_token"] == deal["hold_token"]

def test_payment_challenge_contains_razorpay_rail():
    proposal, _ = create_held_transaction(
        transaction_id="txn_payment_test_002",
    )
    response = client.get(
        f"/api/v1/agent/transactions/{proposal['transaction_id']}/payment"
    )
    assert response.status_code == 402
    assert response.json()["settlement_rail"] == "razorpay"

def test_payment_challenge_requires_held_transaction():
    proposal, _ = create_held_transaction(
        transaction_id="txn_payment_test_003",
    )
    transaction_store.update_state(
        proposal["transaction_id"],
        TransactionState.RELEASED,
        timestamp=int(time.time()),
        reason="Test release.",
    )
    response = client.get(
        f"/api/v1/agent/transactions/{proposal['transaction_id']}/payment"
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "INVALID_TRANSACTION_STATE"

def test_payment_challenge_rejects_unknown_transaction():
    response = client.get(
        "/api/v1/agent/transactions/does-not-exist/payment"
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "TRANSACTION_NOT_FOUND"