import base64
import time
import pytest
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
from app.core.mandate import canonicalize_mandate
from app.main import app
from app.models import Mandate, SpendingConstraints
from app.api.negotiate import inventory
from app.services.deal_store import deal_store

@pytest.fixture(autouse=True)
def reset_inventory():
    inventory._inventory["LAPTOP-PRO-01"].available_quantity = 10
    inventory._inventory["PHONE-PRO-01"].available_quantity = 20
    inventory._inventory["HEADPHONES-01"].available_quantity = 50
    inventory._holds.clear()
    deal_store.clear()

client = TestClient(app)

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
        mandate_id="mnd_api_test_001",
        subject="buyer_agent_test",
        merchant_id="merchant_demo_01",
        constraints=SpendingConstraints(
            max_spend=max_spend,
            currency="INR",
            allowed_categories=[category],
            max_quantity=max_quantity,
        ),
        issued_at=now,
        expires_at=now + 300,
        nonce="api_test_nonce_123456",
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
    price: int = 4800,
    category: str = "electronics",
    quantity: int = 1,
    max_spend: int = 5000,
):
    return {
        "transaction_id": "txn_api_test_001",
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

def test_valid_proposal_is_accepted():
    response = client.post(
        "/api/v1/agent/negotiate",
        json=make_proposal(),
    )
    assert response.status_code == 200

    data = response.json()
    assert data["transaction_id"] == "txn_api_test_001"
    assert data["sku"] == "LAPTOP-PRO-01"
    assert data["approved_unit_price"] == 4800
    assert data["total_amount"] == 4800
    assert data["state"] == "HELD"

def test_budget_violation_is_rejected():
    response = client.post(
        "/api/v1/agent/negotiate",
        json=make_proposal(
            price=4800,
            max_spend=4000,
        ),
    )
    assert response.status_code == 401

    data = response.json()
    assert data["detail"]["code"] == "BUDGET_EXCEEDED"

def test_discount_violation_is_rejected():
    response = client.post(
        "/api/v1/agent/negotiate",
        json=make_proposal(
            price=4500,
        ),
    )
    assert response.status_code == 403

    data = response.json()
    assert (
        data["detail"]["code"]
        == "RULE_MAX_DISCOUNT_EXCEEDED"
    )

def test_wrong_merchant_is_rejected():
    proposal = make_proposal()
    proposal["merchant_id"] = "another_merchant"

    response = client.post(
        "/api/v1/agent/negotiate",
        json=proposal,
    )
    assert response.status_code == 403

    data = response.json()
    assert data["detail"]["code"] == "MERCHANT_MISMATCH"

def test_valid_proposal_creates_inventory_hold():
    before = inventory.get_available_quantity(
        "LAPTOP-PRO-01"
    )

    response = client.post(
        "/api/v1/agent/negotiate",
        json=make_proposal(),
    )
    assert response.status_code == 200

    data = response.json()
    assert data["state"] == "HELD"
    assert data["hold_token"] != "PENDING_HOLD"
    assert data["expires_at"] > int(time.time())

    after = inventory.get_available_quantity(
        "LAPTOP-PRO-01"
    )
    assert after == before - 1

def test_insufficient_inventory_is_rejected():
    # inventory._inventory["LAPTOP-PRO-01"].available_quantity = 3
    inventory.create_hold(
        transaction_id="setup_txn_001",
        sku="LAPTOP-PRO-01",
        quantity=5,
    )

    inventory.create_hold(
        transaction_id="setup_txn_002",
        sku="LAPTOP-PRO-01",
        quantity=5,
    )

    response = client.post(
        "/api/v1/agent/negotiate",
        json=make_proposal(
            quantity=4,
            max_spend=5_000_000,
        ),
    )
    # print("\nSTATUS:", response.status_code)
    # print("RESPONSE:", response.json())
    assert response.status_code == 409

    data = response.json()
    assert data["detail"]["code"] == "INSUFFICIENT_INVENTORY"

def test_negotiate_rejects_price_below_deterministic_floor():
    response = client.post(
        "/api/v1/agent/negotiate",
        json=make_proposal(
            price=4500,
        ),
    )
    assert response.status_code == 403

    data = response.json()
    assert data["detail"]["code"] == (
        "RULE_MAX_DISCOUNT_EXCEEDED"
    )

def test_negotiate_accepts_exact_floor_price():
    response = client.post(
        "/api/v1/agent/negotiate",
        json=make_proposal(
            price=4600,
        ),
    )
    assert response.status_code == 200

    data = response.json()
    assert data["approved_unit_price"] == 4600