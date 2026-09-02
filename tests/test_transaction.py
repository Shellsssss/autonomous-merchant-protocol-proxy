import pytest
from app.core.transaction import (
    TransactionState,
    TransactionStateError,
    TransactionStateMachine,
)

def test_transaction_starts_as_proposed():
    transaction = TransactionStateMachine()
    assert transaction.state == TransactionState.PROPOSED

def test_proposed_can_become_validated():
    transaction = TransactionStateMachine()
    result = transaction.transition(TransactionState.VALIDATED)
    assert result == TransactionState.VALIDATED
    assert transaction.state == TransactionState.VALIDATED

def test_validated_can_become_held():
    transaction = TransactionStateMachine()
    transaction.transition(TransactionState.VALIDATED)
    transaction.transition(TransactionState.HELD)
    assert transaction.state == TransactionState.HELD

def test_held_can_become_payment_pending():
    transaction = TransactionStateMachine()
    transaction.transition(TransactionState.VALIDATED)
    transaction.transition(TransactionState.HELD)
    transaction.transition(TransactionState.PAYMENT_PENDING)
    assert transaction.state == TransactionState.PAYMENT_PENDING

def test_payment_pending_can_become_payment_verified():
    transaction = TransactionStateMachine()
    transaction.transition(TransactionState.VALIDATED)
    transaction.transition(TransactionState.HELD)
    transaction.transition(TransactionState.PAYMENT_PENDING)
    result = transaction.transition(TransactionState.PAYMENT_VERIFIED)
    assert result == TransactionState.PAYMENT_VERIFIED
    assert transaction.state == TransactionState.PAYMENT_VERIFIED

def test_payment_verified_can_become_settling():
    transaction = TransactionStateMachine()
    transaction.transition(TransactionState.VALIDATED)
    transaction.transition(TransactionState.HELD)
    transaction.transition(TransactionState.PAYMENT_PENDING)
    transaction.transition(TransactionState.PAYMENT_VERIFIED)
    result = transaction.transition(TransactionState.SETTLING)
    assert result == TransactionState.SETTLING
    assert transaction.state == TransactionState.SETTLING

def test_settling_can_become_settled():
    transaction = TransactionStateMachine()
    transaction.transition(TransactionState.VALIDATED)
    transaction.transition(TransactionState.HELD)
    transaction.transition(TransactionState.PAYMENT_PENDING)
    transaction.transition(TransactionState.PAYMENT_VERIFIED)
    transaction.transition(TransactionState.SETTLING)
    result = transaction.transition(TransactionState.SETTLED)
    assert result == TransactionState.SETTLED
    assert transaction.state == TransactionState.SETTLED

def test_settled_can_become_inventory_committed():
    transaction = TransactionStateMachine()
    transaction.transition(TransactionState.VALIDATED)
    transaction.transition(TransactionState.HELD)
    transaction.transition(TransactionState.PAYMENT_PENDING)
    transaction.transition(TransactionState.PAYMENT_VERIFIED)
    transaction.transition(TransactionState.SETTLING)
    transaction.transition(TransactionState.SETTLED)
    result = transaction.transition(TransactionState.INVENTORY_COMMITTED)
    assert result == TransactionState.INVENTORY_COMMITTED
    assert transaction.state == TransactionState.INVENTORY_COMMITTED

def test_inventory_committed_can_become_completed():
    transaction = TransactionStateMachine()
    transaction.transition(TransactionState.VALIDATED)
    transaction.transition(TransactionState.HELD)
    transaction.transition(TransactionState.PAYMENT_PENDING)
    transaction.transition(TransactionState.PAYMENT_VERIFIED)
    transaction.transition(TransactionState.SETTLING)
    transaction.transition(TransactionState.SETTLED)
    transaction.transition(TransactionState.INVENTORY_COMMITTED)
    result = transaction.transition(TransactionState.COMPLETED)
    assert result == TransactionState.COMPLETED
    assert transaction.state == TransactionState.COMPLETED

def test_held_can_expire():
    transaction = TransactionStateMachine()
    transaction.transition(TransactionState.VALIDATED)
    transaction.transition(TransactionState.HELD)
    transaction.transition(TransactionState.EXPIRED)
    assert transaction.state == TransactionState.EXPIRED

def test_held_can_be_released():
    transaction = TransactionStateMachine()
    transaction.transition(TransactionState.VALIDATED)
    transaction.transition(TransactionState.HELD)
    transaction.transition(TransactionState.RELEASED)
    assert transaction.state == TransactionState.RELEASED

def test_invalid_proposed_to_settled_transition_is_rejected():
    transaction = TransactionStateMachine()
    with pytest.raises(TransactionStateError):
        transaction.transition(TransactionState.SETTLED)

def test_invalid_payment_pending_to_settled_transition_is_rejected():
    transaction = TransactionStateMachine()
    transaction.transition(TransactionState.VALIDATED)
    transaction.transition(TransactionState.HELD)
    transaction.transition(TransactionState.PAYMENT_PENDING)
    with pytest.raises(TransactionStateError):
        transaction.transition(TransactionState.SETTLED)

def test_expired_transaction_cannot_be_settled():
    transaction = TransactionStateMachine()
    transaction.transition(TransactionState.VALIDATED)
    transaction.transition(TransactionState.HELD)
    transaction.transition(TransactionState.EXPIRED)
    with pytest.raises(TransactionStateError):
        transaction.transition(TransactionState.SETTLED)

def test_released_transaction_cannot_be_settled():
    transaction = TransactionStateMachine()
    transaction.transition(TransactionState.VALIDATED)
    transaction.transition(TransactionState.HELD)
    transaction.transition(TransactionState.RELEASED)
    with pytest.raises(TransactionStateError):
        transaction.transition(TransactionState.SETTLED)

def test_completed_transaction_is_terminal():
    transaction = TransactionStateMachine()
    transaction.transition(TransactionState.VALIDATED)
    transaction.transition(TransactionState.HELD)
    transaction.transition(TransactionState.PAYMENT_PENDING)
    transaction.transition(TransactionState.PAYMENT_VERIFIED)
    transaction.transition(TransactionState.SETTLING)
    transaction.transition(TransactionState.SETTLED)
    transaction.transition(TransactionState.INVENTORY_COMMITTED)
    transaction.transition(TransactionState.COMPLETED)
    with pytest.raises(TransactionStateError):
        transaction.transition(TransactionState.HELD)

def test_can_transition_does_not_mutate_state():
    transaction = TransactionStateMachine()
    assert transaction.can_transition(TransactionState.VALIDATED)
    assert transaction.state == TransactionState.PROPOSED

def test_completed_cannot_transition():
    transaction = TransactionStateMachine(initial_state=TransactionState.COMPLETED)
    assert not transaction.can_transition(TransactionState.PROPOSED)
    with pytest.raises(TransactionStateError):
        transaction.transition(TransactionState.PROPOSED)