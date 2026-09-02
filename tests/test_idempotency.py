import pytest
from app.core.idempotency import (
    IdempotencyConflictError,
    IdempotencyLedger,
    ReplayDetectedError,
)

def test_request_hash_is_deterministic():
    ledger = IdempotencyLedger()
    payload_a = {
        "amount": 4800,
        "currency": "INR",
    }
    payload_b = {
        "currency": "INR",
        "amount": 4800,
    }

    assert (
        ledger.request_hash(payload_a)
        == ledger.request_hash(payload_b)
    )

def test_different_payloads_have_different_hashes():
    ledger = IdempotencyLedger()
    payload_a = {
        "amount": 4800,
    }
    payload_b = {
        "amount": 5000,
    }

    assert (
        ledger.request_hash(payload_a)
        != ledger.request_hash(payload_b)
    )

def test_nonce_can_only_be_consumed_once():
    ledger = IdempotencyLedger()
    ledger.consume_nonce("nonce_123")
    with pytest.raises(ReplayDetectedError):
        ledger.consume_nonce("nonce_123")

def test_different_nonces_are_allowed():
    ledger = IdempotencyLedger()
    ledger.consume_nonce("nonce_123")
    ledger.consume_nonce("nonce_456")

def test_idempotency_returns_cached_response():
    ledger = IdempotencyLedger()
    payload = {
        "transaction_id": "txn_001",
        "amount": 4800,
    }
    first_response = {
        "status": "SETTLED",
        "payment_id": "pay_001",
    }
    ledger.store(
        key="txn_001",
        payload=payload,
        response=first_response,
    )

    result = ledger.get("txn_001")
    assert result == first_response

def test_same_idempotency_key_with_same_payload_is_allowed():
    ledger = IdempotencyLedger()
    payload = {
        "amount": 4800,
    }
    response = {
        "status": "SETTLED",
    }
    ledger.store(
        key="txn_001",
        payload=payload,
        response=response,
    )
    ledger.store(
        key="txn_001",
        payload=payload,
        response=response,
    )

    assert ledger.get("txn_001") == response

def test_same_key_with_modified_payload_is_rejected():
    ledger = IdempotencyLedger()
    ledger.store(
        key="txn_001",
        payload={
            "amount": 4800,
        },
        response={
            "status": "SETTLED",
        },
    )

    with pytest.raises(IdempotencyConflictError):
        ledger.store(
            key="txn_001",
            payload={
                "amount": 100,
            },
            response={
                "status": "SETTLED",
            },
        )

def test_execute_runs_operation_once():
    ledger = IdempotencyLedger()
    calls = []

    def payment_operation():
        calls.append("payment")
        return {
            "payment_id": "pay_001",
            "status": "CAPTURED",
        }

    payload = {
        "transaction_id": "txn_001",
        "amount": 4800,
    }
    first = ledger.execute(
        key="txn_001",
        payload=payload,
        nonce="nonce_001",
        timestamp=1000,
        operation=payment_operation,
    )
    second = ledger.execute(
        key="txn_001",
        payload=payload,
        nonce="nonce_002",
        timestamp=1001,
        operation=payment_operation,
    )

    assert first == second
    assert calls == ["payment"]

def test_execute_rejects_replayed_nonce():
    ledger = IdempotencyLedger()
    calls = []

    def operation():
        calls.append("executed")
        return {"status": "OK"}

    payload = {
        "amount": 4800,
    }
    ledger.execute(
        key="txn_001",
        payload=payload,
        nonce="nonce_001",
        timestamp=1000,
        operation=operation,
    )

    with pytest.raises(ReplayDetectedError):
        ledger.execute(
            key="txn_002",
            payload=payload,
            nonce="nonce_001",
            timestamp=1001,
            operation=operation,
        )

    assert calls == ["executed"]

def test_execute_rejects_modified_payload_with_same_key():
    ledger = IdempotencyLedger()

    def operation():
        return {
            "status": "CAPTURED",
        }

    ledger.execute(
        key="txn_001",
        payload={
            "amount": 4800,
        },
        nonce="nonce_001",
        timestamp=1000,
        operation=operation,
    )

    with pytest.raises(IdempotencyConflictError):
        ledger.execute(
            key="txn_001",
            payload={
                "amount": 100,
            },
            nonce="nonce_002",
            timestamp=1001,
            operation=operation,
        )