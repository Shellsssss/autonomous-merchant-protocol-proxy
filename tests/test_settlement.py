import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.api.negotiate import inventory
from app.api.settle import settlement_ledger
import app.api.settle as settle_module
from app.services.deal_store import deal_store
from app.services import razorpay_adapter as razorpay_module
from app.services.razorpay_adapter import RazorpayOrder
from app.core.transaction_store import transaction_store

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    # Reset inventory
    inventory._inventory["LAPTOP-PRO-01"].available_quantity = 10
    inventory._inventory["PHONE-PRO-01"].available_quantity = 20
    inventory._inventory["HEADPHONES-01"].available_quantity = 50
    inventory._holds.clear()

    # Reset transaction store
    transaction_store.clear()

    # Reset settlement idempotency state
    settlement_ledger._records.clear()
    settlement_ledger._used_nonces.clear()

    # Reset deal store
    deal_store._deals.clear()

    # Mock Razorpay for settlement tests
    class FakeRazorpayAdapter:
        def create_order(
            self,
            *,
            transaction_id: str,
            amount: int,
            currency: str,
        ) -> RazorpayOrder:
            return RazorpayOrder(
                order_id=f"order_test_{transaction_id}",
                amount=amount,
                currency=currency,
                status="created",
            )
    monkeypatch.setattr(
        settle_module,
        "razorpay_adapter",
        FakeRazorpayAdapter(),
    )

def make_proposal(
    *,
    price: int = 4800,
    quantity: int = 1,
):
    # Import the existing test helper's structure if your
    # PurchaseProposal requires additional fields.
    from tests.test_negotiate import make_proposal as negotiate_proposal

    return negotiate_proposal(
        price=price,
        quantity=quantity,
    )

def create_negotiated_deal():
    response = client.post(
        "/api/v1/agent/negotiate",
        json=make_proposal(),
    )
    assert response.status_code == 200

    data = response.json()
    assert data["state"] == "HELD"
    assert data["hold_token"]
    assert data["transaction_id"]

    return data

def test_settlement_requires_idempotency_key():
    deal = create_negotiated_deal()
    response = client.post(
        "/api/v1/agent/settle",
        json={
            "transaction_id": deal["transaction_id"],
            "hold_token": deal["hold_token"],
            "nonce": "nonce_settlement_001",
        },
    )
    assert response.status_code == 400

    data = response.json()
    assert data["detail"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"

def test_valid_settlement_succeeds():
    deal = create_negotiated_deal()
    response = client.post(
        "/api/v1/agent/settle",
        headers={
            "Idempotency-Key": "settlement-key-001",
        },
        json={
            "transaction_id": deal["transaction_id"],
            "hold_token": deal["hold_token"],
            "nonce": "nonce_settlement_002",
        },
    )
    print("STATUS:", response.status_code)
    print("RESPONSE:", response.json())
    assert response.status_code == 200

    data = response.json()
    assert data["transaction_id"] == deal["transaction_id"]
    assert data["status"] == "SETTLED"
    assert data["payment_id"]
    assert data["amount"] == 4800
    assert data["currency"] == "INR"
    assert data["receipt_digest"]

def test_successful_settlement_commits_inventory():
    deal = create_negotiated_deal()
    before = inventory.get_available_quantity(
        "LAPTOP-PRO-01"
    )
    response = client.post(
        "/api/v1/agent/settle",
        headers={
            "Idempotency-Key": "settlement-key-002",
        },
        json={
            "transaction_id": deal["transaction_id"],
            "hold_token": deal["hold_token"],
            "nonce": "nonce_settlement_003",
        },
    )
    assert response.status_code == 200

    after = inventory.get_available_quantity(
        "LAPTOP-PRO-01"
    )
    # One unit was held and then committed.
    assert before == 9
    assert after == 9

def test_invalid_hold_token_is_rejected():
    deal = create_negotiated_deal()
    response = client.post(
        "/api/v1/agent/settle",
        headers={
            "Idempotency-Key": "settlement-key-003",
        },
        json={
            "transaction_id": deal["transaction_id"],
            "hold_token": "invalid-hold-token",
            "nonce": "nonce_settlement_004",
        },
    )
    assert response.status_code == 409

def test_transaction_and_hold_must_match():
    deal = create_negotiated_deal()
    response = client.post(
        "/api/v1/agent/settle",
        headers={
            "Idempotency-Key": "settlement-key-004",
        },
        json={
            "transaction_id": "different-transaction",
            "hold_token": deal["hold_token"],
            "nonce": "nonce_settlement_005",
        },
    )
    assert response.status_code == 409

def test_replayed_nonce_is_rejected():
    deal = create_negotiated_deal()
    first = client.post(
        "/api/v1/agent/settle",
        headers={
            "Idempotency-Key": "settlement-key-005",
        },
        json={
            "transaction_id": deal["transaction_id"],
            "hold_token": deal["hold_token"],
            "nonce": "nonce_settlement_006",
        },
    )
    assert first.status_code == 200

    # New idempotency key, but same nonce.
    second = client.post(
        "/api/v1/agent/settle",
        headers={
            "Idempotency-Key": "settlement-key-006",
        },
        json={
            "transaction_id": deal["transaction_id"],
            "hold_token": deal["hold_token"],
            "nonce": "nonce_settlement_006",
        },
    )
    assert second.status_code == 409

    data = second.json()
    assert data["detail"]["code"] == "REPLAY_DETECTED"

def test_same_idempotency_key_returns_same_result():
    deal = create_negotiated_deal()
    payload = {
        "transaction_id": deal["transaction_id"],
        "hold_token": deal["hold_token"],
        "nonce": "nonce_settlement_007",
    }

    first = client.post(
        "/api/v1/agent/settle",
        headers={
            "Idempotency-Key": "settlement-key-007",
        },
        json=payload,
    )
    assert first.status_code == 200

    # Same key + same payload.
    # Use a fresh nonce because the idempotency key should
    # return the cached result before nonce replay matters.
    second = client.post(
        "/api/v1/agent/settle",
        headers={
            "Idempotency-Key": "settlement-key-007",
        },
        json={
            **payload,
            "nonce": "nonce_settlement_008",
        },
    )
    assert second.status_code == 200
    assert second.json() == first.json()

def test_same_idempotency_key_with_modified_payload_is_rejected():
    deal = create_negotiated_deal()
    first = client.post(
        "/api/v1/agent/settle",
        headers={
            "Idempotency-Key": "settlement-key-008",
        },
        json={
            "transaction_id": deal["transaction_id"],
            "hold_token": deal["hold_token"],
            "nonce": "nonce_settlement_009",
        },
    )
    assert first.status_code == 200

    second = client.post(
        "/api/v1/agent/settle",
        headers={
            "Idempotency-Key": "settlement-key-008",
        },
        json={
            "transaction_id": deal["transaction_id"],
            "hold_token": "different-hold",
            "nonce": "nonce_settlement_010",
        },
    )
    assert second.status_code == 409

    data = second.json()
    assert data["detail"]["code"] == "IDEMPOTENCY_CONFLICT"