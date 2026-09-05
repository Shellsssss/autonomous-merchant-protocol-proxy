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

    # Reset payment verification legder
    settle_module.payment_verification_ledger._records.clear()
    settle_module.payment_verification_ledger._used_nonces.clear()

    # Reset payment settlement ledger
    settle_module.payment_settlement_ledger._records.clear()
    settle_module.payment_settlement_ledger._used_nonces.clear()

    # Reset inventory commit ledger
    settle_module.inventory_commit_ledger._records.clear()
    settle_module.inventory_commit_ledger._used_nonces.clear()

    # Reset fullfilment ledger
    settle_module.fulfillment_ledger._records.clear()
    settle_module.fulfillment_ledger._used_nonces.clear()

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

def verify_payment(deal):
    payment = settle_deal(deal)
    order_id = payment["payment_id"]
    payment_id = "pay_test_123"
    response = client.post(
        "/api/v1/agent/verify-payment",
        headers={
            "Idempotency-Key": f"verify-{deal['transaction_id']}",
        },
        json={
            "transaction_id": deal["transaction_id"],
            "order_id": order_id,
            "payment_id": payment_id,
            "signature": f"valid_{order_id}_{payment_id}",
        },
    )
    assert response.status_code == 200
    return response.json()

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
    assert response.status_code == 200

    data = response.json()
    assert data["transaction_id"] == deal["transaction_id"]
    assert data["status"] == "PAYMENT_PENDING"
    assert data["payment_id"]
    assert data["amount"] == deal["total_amount"]
    assert data["currency"] == deal["currency"]

    transaction = transaction_store.get(
        deal["transaction_id"]
    )
    assert transaction.state == TransactionState.PAYMENT_PENDING
    assert transaction.payment_order_id == data["payment_id"]
    assert transaction.payment_id is None

# def test_successful_settlement_commits_inventory():
#     deal = create_negotiated_deal()
#     before = inventory.get_available_quantity(
#         "LAPTOP-PRO-01"
#     )
#     response = client.post(
#         "/api/v1/agent/settle",
#         headers={
#             "Idempotency-Key": "settlement-key-002",
#         },
#         json={
#             "transaction_id": deal["transaction_id"],
#             "hold_token": deal["hold_token"],
#             "nonce": "nonce_settlement_003",
#         },
#     )
#     assert response.status_code == 200

#     after = inventory.get_available_quantity(
#         "LAPTOP-PRO-01"
#     )
#     # One unit was held and then committed.
#     assert before == 9
#     assert after == 9

def test_successful_settlement_keeps_inventory_held():
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
    # The inventory was already reserved during negotiation.
    # Payment order creation must not commit the inventory.
    assert before == 9
    assert after == 9

    hold = inventory.get_hold(
        deal["hold_token"]
    )
    assert hold.state == "HELD"

    transaction = transaction_store.get(
        deal["transaction_id"]
    )
    assert transaction.state == TransactionState.PAYMENT_PENDING

    data = response.json()
    assert data["status"] == "PAYMENT_PENDING"
    assert data["payment_id"]
    assert data["amount"] == deal["total_amount"]
    assert data["currency"] == deal["currency"]

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

def test_settlement_moves_transaction_to_payment_pending():
    proposal = make_proposal()
    negotiate_response = client.post(
        "/api/v1/agent/negotiate",
        json=proposal,
    )
    assert negotiate_response.status_code == 200

    transaction_id = proposal["transaction_id"]
    transaction = transaction_store.get(transaction_id)
    assert transaction.state == TransactionState.HELD

    response = client.post(
        "/api/v1/agent/settle",
        json={
            "transaction_id": transaction_id,
            "hold_token": negotiate_response.json()["hold_token"],
            "nonce": "settlement_test_nonce_123456",
        },
        headers={
            "Idempotency-Key": "settlement-state-test-001",
        },
    )
    assert response.status_code in {200, 402, 409, 500}

    transaction = transaction_store.get(transaction_id)
    assert transaction.state == TransactionState.PAYMENT_PENDING

def settle_payment(deal):
    verification = verify_payment(deal)
    response = client.post(
        "/api/v1/agent/settle-payment",
        headers={
            "Idempotency-Key": f"payment-settle-{deal['transaction_id']}",
        },
        json={
            "transaction_id": deal["transaction_id"],
            "payment_id": verification["payment_id"],
        },
    )
    assert response.status_code == 200
    return response.json()

def test_settled_payment_can_commit_inventory():
    deal = create_negotiated_deal()
    before = inventory.get_available_quantity(
        "LAPTOP-PRO-01"
    )
    settle_payment(deal)
    transaction = transaction_store.get(
        deal["transaction_id"]
    )
    assert transaction.state == TransactionState.SETTLED

    response = client.post(
        "/api/v1/agent/commit-inventory",
        headers={
            "Idempotency-Key": f"inventory-commit-{deal['transaction_id']}",
        },
        json={
            "transaction_id": deal["transaction_id"],
            "hold_token": deal["hold_token"],
        },
    )
    assert response.status_code == 200

    data = response.json()
    assert data["transaction_id"] == deal["transaction_id"]
    assert data["status"] == "INVENTORY_COMMITTED"

    after = inventory.get_available_quantity(
        "LAPTOP-PRO-01"
    )
    # Inventory was already removed from available stock
    # when the hold was created.
    assert before == 9
    assert after == 9

    hold = inventory.get_hold(
        deal["hold_token"]
    )
    assert hold.state == "COMMITTED"

    transaction = transaction_store.get(
        deal["transaction_id"]
    )
    assert transaction.state == TransactionState.INVENTORY_COMMITTED

def test_unsettled_payment_cannot_commit_inventory():
    deal = create_negotiated_deal()
    settle_deal(deal)
    verify_payment(deal)
    response = client.post(
        "/api/v1/agent/commit-inventory",
        headers={
            "Idempotency-Key": f"inventory-commit-{deal['transaction_id']}",
        },
        json={
            "transaction_id": deal["transaction_id"],
            "hold_token": deal["hold_token"],
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "INVALID_TRANSACTION_STATE"

    transaction = transaction_store.get(
        deal["transaction_id"]
    )
    assert transaction.state == TransactionState.PAYMENT_VERIFIED

def test_inventory_commit_rejects_invalid_hold_token():
    deal = create_negotiated_deal()
    settle_payment(deal)
    response = client.post(
        "/api/v1/agent/commit-inventory",
        headers={
                "Idempotency-Key": f"inventory-commit-{deal['transaction_id']}",
            },
        json={
            "transaction_id": deal["transaction_id"],
            "hold_token": "invalid-hold-token",
        },
    )
    assert response.status_code == 409

    transaction = transaction_store.get(
        deal["transaction_id"]
    )
    assert transaction.state == TransactionState.SETTLED

    hold = inventory.get_hold(
        deal["hold_token"]
    )
    assert hold.state == "HELD"

def commit_inventory(deal):
    settle_payment(deal)
    response = client.post(
        "/api/v1/agent/commit-inventory",
        headers={
            "Idempotency-Key": f"inventory-commit-{deal['transaction_id']}",
        },
        json={
            "transaction_id": deal["transaction_id"],
            "hold_token": deal["hold_token"],
        },
    )
    assert response.status_code == 200
    return response.json()

def test_committed_inventory_can_be_fulfilled():
    deal = create_negotiated_deal()
    commit_inventory(deal)
    response = client.post(
        "/api/v1/agent/fulfill",
        headers={
            "Idempotency-Key": f"fulfill-{deal["transaction_id"]}",
        },
        json={
            "transaction_id": deal["transaction_id"],
            "hold_token": deal["hold_token"],
        },
    )
    assert response.status_code == 200

    data = response.json()
    assert data["transaction_id"] == deal["transaction_id"]
    assert data["receipt_id"]
    assert data["status"] == "COMPLETED"
    assert data["receipt_digest"]

    transaction = transaction_store.get(
        deal["transaction_id"]
    )
    assert transaction.state == TransactionState.COMPLETED
    assert transaction.receipt_id == data["receipt_id"]

    receipt = receipt_store.get(data["receipt_id"])
    assert receipt.transaction_id == deal["transaction_id"]
    assert receipt.payment_id == transaction.payment_id
    assert receipt.amount == deal["total_amount"]
    assert receipt.currency == deal["currency"]
    assert receipt.sku == deal["sku"]
    assert receipt.quantity == deal["quantity"]
    assert receipt.receipt_digest == data["receipt_digest"]

def test_fulfillment_requires_inventory_commitment():
    deal = create_negotiated_deal()
    settle_payment(deal)
    response = client.post(
        "/api/v1/agent/fulfill",
        headers={
            "Idempotency-Key": f"fulfill-{deal["transaction_id"]}",
        },
        json={
            "transaction_id": deal["transaction_id"],
            "hold_token": deal["hold_token"],
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "INVALID_TRANSACTION_STATE"

    transaction = transaction_store.get(
        deal["transaction_id"]
    )
    assert transaction.state == TransactionState.SETTLED

def test_completed_transaction_cannot_be_fulfilled_again():
    deal = create_negotiated_deal()
    commit_inventory(deal)
    first = client.post(
        "/api/v1/agent/fulfill",
        headers={
            "Idempotency-Key": f"fulfill-again-{deal['transaction_id']}",
        },
        json={
            "transaction_id": deal["transaction_id"],
            "hold_token": deal["hold_token"],
        },
    )
    assert first.status_code == 200

    second = client.post(
        "/api/v1/agent/fulfill",
        headers={
            "Idempotency-Key": f"fulfill-{deal['transaction_id']}",
        },
        json={
            "transaction_id": deal["transaction_id"],
            "hold_token": deal["hold_token"],
        },
    )
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "INVALID_TRANSACTION_STATE"

    transaction = transaction_store.get(
        deal["transaction_id"]
    )
    assert transaction.state == TransactionState.COMPLETED

def test_settle_payment_is_idempotent():
    deal = create_negotiated_deal()

    verification = verify_payment(deal)

    headers = {
        "Idempotency-Key": f"payment-settle-idempotent-{deal['transaction_id']}",
    }

    payload = {
        "transaction_id": deal["transaction_id"],
        "payment_id": verification["payment_id"],
    }

    first_response = client.post(
        "/api/v1/agent/settle-payment",
        headers=headers,
        json=payload,
    )

    assert first_response.status_code == 200

    second_response = client.post(
        "/api/v1/agent/settle-payment",
        headers=headers,
        json=payload,
    )

    assert second_response.status_code == 200
    assert second_response.json() == first_response.json()

def test_settle_payment_rejects_idempotency_key_reuse_with_different_payload():
    deal = create_negotiated_deal()

    verification = verify_payment(deal)

    headers = {
        "Idempotency-Key": f"payment-settle-conflict-{deal['transaction_id']}",
    }

    payload = {
        "transaction_id": deal["transaction_id"],
        "payment_id": verification["payment_id"],
    }

    first_response = client.post(
        "/api/v1/agent/settle-payment",
        headers=headers,
        json=payload,
    )

    assert first_response.status_code == 200

    conflicting_payload = {
        "transaction_id": deal["transaction_id"],
        "payment_id": "different-payment-id",
    }

    second_response = client.post(
        "/api/v1/agent/settle-payment",
        headers=headers,
        json=conflicting_payload,
    )

    assert second_response.status_code == 409
    assert second_response.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"

def test_fulfillment_is_idempotent():
    deal = create_negotiated_deal()
    commit_inventory(deal)

    headers = {
        "Idempotency-Key": f"fulfill-idempotent-{deal['transaction_id']}",
    }

    payload = {
        "transaction_id": deal["transaction_id"],
        "hold_token": deal["hold_token"],
    }

    first = client.post(
        "/api/v1/agent/fulfill",
        headers=headers,
        json=payload,
    )

    assert first.status_code == 200

    second = client.post(
        "/api/v1/agent/fulfill",
        headers=headers,
        json=payload,
    )

    assert second.status_code == 200
    assert second.json() == first.json()

def test_fulfillment_rejects_idempotency_key_reuse_with_different_payload():
    deal = create_negotiated_deal()
    commit_inventory(deal)

    headers = {
        "Idempotency-Key": f"fulfill-conflict-{deal['transaction_id']}",
    }

    first_payload = {
        "transaction_id": deal["transaction_id"],
        "hold_token": deal["hold_token"],
    }

    first = client.post(
        "/api/v1/agent/fulfill",
        headers=headers,
        json=first_payload,
    )

    assert first.status_code == 200

    conflicting_payload = {
        "transaction_id": deal["transaction_id"],
        "hold_token": "different-hold-token",
    }

    second = client.post(
        "/api/v1/agent/fulfill",
        headers=headers,
        json=conflicting_payload,
    )

    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"

def test_razorpay_order_failure_fails_transaction_and_releases_inventory(monkeypatch):
    deal = create_negotiated_deal()

    class FailingRazorpayAdapter:
        def create_order(
            self,
            *,
            transaction_id: str,
            amount: int,
            currency: str,
        ) -> RazorpayOrder:
            from app.services.razorpay_adapter import RazorpayError

            raise RazorpayError(
                "RAZORPAY_ORDER_CREATION_FAILED",
                "Simulated Razorpay failure.",
            )

    monkeypatch.setattr(
        settle_module,
        "razorpay_adapter",
        FailingRazorpayAdapter(),
    )

    response = client.post(
        "/api/v1/agent/settle",
        headers={
            "Idempotency-Key": f"settle-failure-{deal['transaction_id']}",
        },
        json={
            "transaction_id": deal["transaction_id"],
            "hold_token": deal["hold_token"],
            "nonce": f"nonce-failure-{deal['transaction_id']}-123456",
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "RAZORPAY_ORDER_CREATION_FAILED"

    transaction = transaction_store.get(deal["transaction_id"])
    assert transaction.state == TransactionState.FAILED

    hold = inventory.get_hold(deal["hold_token"])
    assert hold.state == "RELEASED"
    assert inventory.get_available_quantity(deal["sku"]) == 10

def test_expired_hold_transitions_transaction_to_expired_and_rejects_settlement():
    deal = create_negotiated_deal()

    transaction = transaction_store.get(deal["transaction_id"])

    hold = inventory.get_hold(deal["hold_token"])
    hold.expires_at = 0

    response = client.post(
        "/api/v1/agent/settle",
        headers={
            "Idempotency-Key": f"settle-expired-{deal['transaction_id']}",
        },
        json={
            "transaction_id": deal["transaction_id"],
            "hold_token": deal["hold_token"],
            "nonce": f"nonce-expired-{deal['transaction_id']}-123456",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "HOLD_EXPIRED"

    transaction = transaction_store.get(deal["transaction_id"])
    assert transaction.state == TransactionState.EXPIRED

    hold = inventory.get_hold(deal["hold_token"])
    assert hold.state == "EXPIRED"