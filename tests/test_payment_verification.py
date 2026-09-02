import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.api.negotiate import inventory
from app.api.settle import settlement_ledger
import app.api.settle as settle_module
from app.services.deal_store import deal_store
from app.services import razorpay_adapter as razorpay_module
from app.services.razorpay_adapter import RazorpayOrder
from app.core.transaction import TransactionState
from app.core.transaction_store import transaction_store
from app.services.receipt_store import receipt_store

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    # Reset inventory
    inventory._inventory["LAPTOP-PRO-01"].available_quantity = 10
    inventory._inventory["PHONE-PRO-01"].available_quantity = 20
    inventory._inventory["HEADPHONES-01"].available_quantity = 50
    inventory._holds.clear()

    # Reset deal store
    deal_store._deals.clear()

    # Reset transaction store
    transaction_store.clear()

    # Reset receipt store
    receipt_store.clear()

    # Reset settlement idempotency state
    settlement_ledger._records.clear()
    settlement_ledger._used_nonces.clear()

    # Reset verification idempotency state
    settle_module.payment_verification_ledger._records.clear()
    settle_module.payment_verification_ledger._used_nonces.clear()

    # Reset settlement idempotency state
    settle_module.payment_settlement_ledger._records.clear()
    settle_module.payment_settlement_ledger._used_nonces.clear()

    # Mock Razorpay for settlement tests
    class FakeRazorpayAdapter:
        def create_order(self, *, transaction_id: str, amount: int, currency: str) -> RazorpayOrder:
            return RazorpayOrder(
                order_id=f"order_test_{transaction_id}",
                amount=amount,
                currency=currency,
                status="created",
            )
        def verify_payment_signature(
            self,
            *,
            order_id: str,
            payment_id: str,
            signature: str,
        ) -> bool:
            return signature == f"valid_{order_id}_{payment_id}"
    monkeypatch.setattr(settle_module, "razorpay_adapter", FakeRazorpayAdapter())

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

def settle_deal(deal):
    response = client.post(
        "/api/v1/agent/settle",
        headers={
            "Idempotency-Key": f"settle-{deal['transaction_id']}",
        },
        json={
            "transaction_id": deal["transaction_id"],
            "hold_token": deal["hold_token"],
            "nonce": f"nonce-{deal['transaction_id']}-123456",
        },
    )
    assert response.status_code == 200
    return response.json()

def test_payment_verification_succeeds():
    deal = create_negotiated_deal()
    payment = settle_deal(deal)
    response = client.post(
        "/api/v1/agent/verify-payment",
        headers={
            "Idempotency-Key": f"verify-{deal['transaction_id']}",
        },
        json={
            "transaction_id": deal["transaction_id"],
            "order_id": payment["payment_id"],
            "payment_id": "pay_test_123",
            "signature": f"valid_{payment['payment_id']}_pay_test_123",
        },
    )
    assert response.status_code == 200

    data = response.json()
    assert data["transaction_id"] == deal["transaction_id"]
    assert data["payment_id"] == "pay_test_123"
    assert data["status"] == "PAYMENT_VERIFIED"

    transaction = transaction_store.get(deal["transaction_id"])
    assert transaction.state == TransactionState.PAYMENT_VERIFIED
    assert transaction.payment_order_id == payment["payment_id"]
    assert transaction.payment_id == "pay_test_123"

def test_invalid_payment_signature_is_rejected():
    deal = create_negotiated_deal()
    payment = settle_deal(deal)
    response = client.post(
        "/api/v1/agent/verify-payment",
        headers={
            "Idempotency-Key": f"verify-{deal['transaction_id']}",
        },
        json={
            "transaction_id": deal["transaction_id"],
            "order_id": payment["payment_id"],
            "payment_id": "pay_test_123",
            "signature": "invalid",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "INVALID_PAYMENT_SIGNATURE"

    transaction = transaction_store.get(deal["transaction_id"])
    assert transaction.state == TransactionState.PAYMENT_PENDING
    assert transaction.payment_id is None

def test_payment_verification_rejects_order_mismatch():
    deal = create_negotiated_deal()
    settle_deal(deal)
    response = client.post(
        "/api/v1/agent/verify-payment",
        headers={
            "Idempotency-Key": f"verify-{deal['transaction_id']}",
        },
        json={
            "transaction_id": deal["transaction_id"],
            "order_id": "order_wrong",
            "payment_id": "pay_test_123",
            "signature": "valid_order_wrong_pay_test_123",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PAYMENT_ORDER_MISMATCH"

    transaction = transaction_store.get(deal["transaction_id"])
    assert transaction.state == TransactionState.PAYMENT_PENDING

def verify_payment(deal):
    payment = settle_deal(deal)
    response = client.post(
        "/api/v1/agent/verify-payment",
        headers={
            "Idempotency-Key": f"verify-{deal['transaction_id']}",
        },
        json={
            "transaction_id": deal["transaction_id"],
            "order_id": payment["payment_id"],
            "payment_id": "pay_test_123",
            "signature": f"valid_{payment['payment_id']}_pay_test_123",
        },
    )
    assert response.status_code == 200
    return response.json()

def test_verified_payment_can_be_settled():
    deal = create_negotiated_deal()
    verification = verify_payment(deal)
    response = client.post(
        "/api/v1/agent/settle-payment",
        json={
            "transaction_id": deal["transaction_id"],
            "payment_id": verification["payment_id"],
        },
    )
    assert response.status_code == 200

    data = response.json()
    assert data["transaction_id"] == deal["transaction_id"]
    assert data["payment_id"] == "pay_test_123"
    assert data["status"] == "SETTLED"

    transaction = transaction_store.get(deal["transaction_id"])
    assert transaction.state == TransactionState.SETTLED
    assert transaction.payment_id == "pay_test_123"

def test_unverified_payment_cannot_be_settled():
    deal = create_negotiated_deal()
    payment = settle_deal(deal)
    response = client.post(
        "/api/v1/agent/settle-payment",
        json={
            "transaction_id": deal["transaction_id"],
            "payment_id": "pay_test_123",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "INVALID_TRANSACTION_STATE"

    transaction = transaction_store.get(deal["transaction_id"])
    assert transaction.state == TransactionState.PAYMENT_PENDING

def test_settlement_rejects_payment_mismatch():
    deal = create_negotiated_deal()
    verify_payment(deal)
    response = client.post(
        "/api/v1/agent/settle-payment",
        json={
            "transaction_id": deal["transaction_id"],
            "payment_id": "pay_wrong",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PAYMENT_MISMATCH"

    transaction = transaction_store.get(deal["transaction_id"])
    assert transaction.state == TransactionState.PAYMENT_VERIFIED

def test_same_verification_idempotency_key_returns_same_result():
    deal = create_negotiated_deal()
    payment = settle_deal(deal)
    order_id = payment["payment_id"]
    payment_id = "pay_test_123"
    signature = f"valid_{order_id}_{payment_id}"
    headers = {"Idempotency-Key": "verify-key-1"}

    payload = {
        "transaction_id": deal["transaction_id"],
        "order_id": order_id,
        "payment_id": payment_id,
        "signature": signature,
    }

    first = client.post(
        "/api/v1/agent/verify-payment",
        json=payload,
        headers=headers,
    )
    second = client.post(
        "/api/v1/agent/verify-payment",
        json=payload,
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()

def test_same_verification_idempotency_key_with_modified_payload_is_rejected():
    deal = create_negotiated_deal()
    payment = settle_deal(deal)
    order_id = payment["payment_id"]
    headers = {"Idempotency-Key": "verify-key-conflict"}

    first_payload = {
        "transaction_id": deal["transaction_id"],
        "order_id": order_id,
        "payment_id": "pay_test_123",
        "signature": f"valid_{order_id}_pay_test_123",
    }
    second_payload = {
        "transaction_id": deal["transaction_id"],
        "order_id": order_id,
        "payment_id": "pay_test_456",
        "signature": f"valid_{order_id}_pay_test_456",
    }

    first = client.post(
        "/api/v1/agent/verify-payment",
        json=first_payload,
        headers=headers,
    )
    second = client.post(
        "/api/v1/agent/verify-payment",
        json=second_payload,
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"