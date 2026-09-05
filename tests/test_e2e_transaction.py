from fastapi.testclient import TestClient
from app.main import app
from app.core.transaction import TransactionState
from app.core.transaction_store import transaction_store
from app.api.negotiate import inventory
from app.services.deal_store import deal_store
from app.services.receipt_store import receipt_store
import app.api.settle as settle_module
from app.services.razorpay_adapter import RazorpayOrder

client = TestClient(app)

def make_proposal(
    *,
    price: int = 4800,
    quantity: int = 1,
):
    from tests.test_negotiate import make_proposal as negotiate_proposal

    return negotiate_proposal(
        price=price,
        quantity=quantity,
    )


def test_complete_autonomous_transaction_flow(monkeypatch):
    inventory._inventory["LAPTOP-PRO-01"].available_quantity = 10
    inventory._holds.clear()
    deal_store._deals.clear()
    transaction_store.clear()
    receipt_store.clear()

    settle_module.settlement_ledger._records.clear()
    settle_module.settlement_ledger._used_nonces.clear()
    settle_module.payment_verification_ledger._records.clear()
    settle_module.payment_verification_ledger._used_nonces.clear()
    settle_module.payment_settlement_ledger._records.clear()
    settle_module.payment_settlement_ledger._used_nonces.clear()
    settle_module.inventory_commit_ledger._records.clear()
    settle_module.inventory_commit_ledger._used_nonces.clear()
    settle_module.fulfillment_ledger._records.clear()
    settle_module.fulfillment_ledger._used_nonces.clear()

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

    monkeypatch.setattr(
        settle_module,
        "razorpay_adapter",
        FakeRazorpayAdapter(),
    )

    # 1. Negotiate and create inventory hold
    negotiate_response = client.post(
        "/api/v1/agent/negotiate",
        json=make_proposal(),
    )

    assert negotiate_response.status_code == 200

    deal = negotiate_response.json()

    transaction_id = deal["transaction_id"]
    hold_token = deal["hold_token"]

    assert deal["state"] == "HELD"
    assert transaction_id
    assert hold_token

    transaction = transaction_store.get(transaction_id)
    assert transaction.state == TransactionState.HELD

    # 2. Request x402 payment challenge
    challenge_response = client.get(
        f"/api/v1/agent/transactions/{transaction_id}/payment"
    )

    assert challenge_response.status_code == 402

    challenge = challenge_response.json()

    assert challenge["protocol"] == "x402"
    assert challenge["transaction_id"] == transaction_id
    assert challenge["hold_token"] == hold_token
    assert challenge["amount"] > 0

    # 3. Create payment order
    settle_response = client.post(
        "/api/v1/agent/settle",
        headers={
            "Idempotency-Key": f"e2e-settle-{transaction_id}",
        },
        json={
            "transaction_id": transaction_id,
            "hold_token": hold_token,
            "nonce": f"e2e-nonce-{transaction_id}-123456",
        },
    )

    assert settle_response.status_code == 200

    payment = settle_response.json()
    order_id = payment["payment_id"]

    assert payment["status"] == "PAYMENT_PENDING"

    transaction = transaction_store.get(transaction_id)
    assert transaction.state == TransactionState.PAYMENT_PENDING
    assert transaction.payment_order_id == order_id

    # 4. Verify Razorpay payment
    payment_id = "pay_test_e2e_123"

    verify_response = client.post(
        "/api/v1/agent/verify-payment",
        headers={
            "Idempotency-Key": f"e2e-verify-{transaction_id}",
        },
        json={
            "transaction_id": transaction_id,
            "order_id": order_id,
            "payment_id": payment_id,
            "signature": f"valid_{order_id}_{payment_id}",
        },
    )

    assert verify_response.status_code == 200
    assert verify_response.json()["status"] == "PAYMENT_VERIFIED"

    transaction = transaction_store.get(transaction_id)
    assert transaction.state == TransactionState.PAYMENT_VERIFIED
    assert transaction.payment_id == payment_id

    # 5. Settle verified payment
    settle_payment_response = client.post(
        "/api/v1/agent/settle-payment",
        headers={
            "Idempotency-Key": f"e2e-payment-settle-{transaction_id}",
        },
        json={
            "transaction_id": transaction_id,
            "payment_id": payment_id,
        },
    )

    assert settle_payment_response.status_code == 200
    assert settle_payment_response.json()["status"] == "SETTLED"

    transaction = transaction_store.get(transaction_id)
    assert transaction.state == TransactionState.SETTLED

    # 6. Commit inventory
    commit_response = client.post(
        "/api/v1/agent/commit-inventory",
        headers={
            "Idempotency-Key": f"e2e-inventory-{transaction_id}",
        },
        json={
            "transaction_id": transaction_id,
            "hold_token": hold_token,
        },
    )

    assert commit_response.status_code == 200
    assert commit_response.json()["status"] == "INVENTORY_COMMITTED"

    transaction = transaction_store.get(transaction_id)
    assert transaction.state == TransactionState.INVENTORY_COMMITTED

    # 7. Fulfill and generate signed receipt
    fulfillment_response = client.post(
        "/api/v1/agent/fulfill",
        headers={
            "Idempotency-Key": f"e2e-fulfill-{transaction_id}",
        },
        json={
            "transaction_id": transaction_id,
            "hold_token": hold_token,
        },
    )

    assert fulfillment_response.status_code == 200

    fulfillment = fulfillment_response.json()

    assert fulfillment["status"] == "COMPLETED"
    assert fulfillment["transaction_id"] == transaction_id
    assert fulfillment["receipt_id"]
    assert fulfillment["receipt_digest"]

    transaction = transaction_store.get(transaction_id)

    assert transaction.state == TransactionState.COMPLETED
    assert transaction.receipt_id == fulfillment["receipt_id"]

    receipt = receipt_store.get(fulfillment["receipt_id"])

    assert receipt.transaction_id == transaction_id
    assert receipt.payment_id == payment_id
    assert receipt.receipt_digest == fulfillment["receipt_digest"]