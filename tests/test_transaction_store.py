import time
import pytest
from app.core.transaction import TransactionState, TransactionStateError
from app.core.transaction_store import (
    TransactionConflictError,
    TransactionNotFoundError,
    TransactionStore,
)
from app.models.transaction import Transaction

def create_transaction(transaction_id="txn_test_001"):
    now = int(time.time())
    return Transaction(
        transaction_id=transaction_id,
        merchant_id="merchant_test",
        created_at=now,
        updated_at=now,
    )

def test_transaction_can_be_created():
    store = TransactionStore()
    transaction = create_transaction()
    result = store.create(transaction)
    assert result == transaction
    assert store.get("txn_test_001") == transaction

def test_duplicate_identical_transaction_is_idempotent():
    store = TransactionStore()
    transaction = create_transaction()
    store.create(transaction)
    result = store.create(transaction)
    assert result == transaction

def test_duplicate_transaction_with_different_data_is_rejected():
    store = TransactionStore()
    first = create_transaction()
    second = first.model_copy(
        update={"merchant_id": "different_merchant"}
    )
    store.create(first)
    with pytest.raises(TransactionConflictError):
        store.create(second)

def test_missing_transaction_is_rejected():
    store = TransactionStore()
    with pytest.raises(TransactionNotFoundError):
        store.get("does_not_exist")

def test_transaction_can_move_from_proposed_to_validated():
    store = TransactionStore()
    store.create(create_transaction())
    result = store.update_state(
        "txn_test_001",
        TransactionState.VALIDATED,
        timestamp=int(time.time()),
    )
    assert result.state == TransactionState.VALIDATED
    assert store.get("txn_test_001").state == TransactionState.VALIDATED

def test_transaction_can_move_from_validated_to_held():
    store = TransactionStore()
    store.create(create_transaction())
    store.update_state(
        "txn_test_001",
        TransactionState.VALIDATED,
        timestamp=int(time.time()),
    )
    result = store.update_state(
        "txn_test_001",
        TransactionState.HELD,
        timestamp=int(time.time()),
    )
    assert result.state == TransactionState.HELD

def test_invalid_transaction_transition_is_rejected():
    store = TransactionStore()
    store.create(create_transaction())
    with pytest.raises(TransactionStateError):
        store.update_state(
            "txn_test_001",
            TransactionState.SETTLED,
            timestamp=int(time.time()),
        )

def test_state_change_creates_event():
    store = TransactionStore()
    store.create(create_transaction())
    store.update_state(
        "txn_test_001",
        TransactionState.VALIDATED,
        timestamp=int(time.time()),
        reason="Validation succeeded.",
    )
    events = store.get_events("txn_test_001")

    assert len(events) == 1
    assert events[0].transaction_id == "txn_test_001"
    assert events[0].from_state == TransactionState.PROPOSED
    assert events[0].to_state == TransactionState.VALIDATED
    assert events[0].reason == "Validation succeeded."

def test_transaction_events_are_returned_in_order():
    store = TransactionStore()
    store.create(create_transaction())
    now = int(time.time())
    store.update_state(
        "txn_test_001",
        TransactionState.VALIDATED,
        timestamp=now,
    )
    store.update_state(
        "txn_test_001",
        TransactionState.HELD,
        timestamp=now + 1,
    )
    events = store.get_events("txn_test_001")

    assert len(events) == 2
    assert events[0].to_state == TransactionState.VALIDATED
    assert events[1].to_state == TransactionState.HELD