from enum import Enum

class TransactionState(str, Enum):
    PROPOSED = "PROPOSED"
    VALIDATED = "VALIDATED"
    HELD = "HELD"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAYMENT_VERIFIED = "PAYMENT_VERIFIED"
    SETTLING = "SETTLING"
    SETTLED = "SETTLED"
    INVENTORY_COMMITTED = "INVENTORY_COMMITTED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    RELEASED = "RELEASED"
    FAILED = "FAILED"

class TransactionStateError(Exception):
    def __init__(self, current_state: TransactionState, requested_state: TransactionState):
        self.current_state = current_state
        self.requested_state = requested_state

        super().__init__(
            f"Invalid transaction transition: "
            f"{current_state.value} -> {requested_state.value}"
        )

_ALLOWED_TRANSITIONS = {
    TransactionState.PROPOSED: {
        TransactionState.VALIDATED,
        TransactionState.FAILED,
    },
    TransactionState.VALIDATED: {
        TransactionState.HELD,
        TransactionState.FAILED,
    },
    TransactionState.HELD: {
        TransactionState.PAYMENT_PENDING,
        TransactionState.EXPIRED,
        TransactionState.RELEASED,
        TransactionState.FAILED,
    },
    TransactionState.PAYMENT_PENDING: {
        TransactionState.PAYMENT_VERIFIED,
        TransactionState.EXPIRED,
        TransactionState.FAILED,
    },
    TransactionState.PAYMENT_VERIFIED: {
        TransactionState.SETTLING,
        TransactionState.FAILED,
    },
    TransactionState.SETTLING: {
        TransactionState.SETTLED,
        TransactionState.FAILED,
    },
    TransactionState.SETTLED: {
        TransactionState.INVENTORY_COMMITTED,
        TransactionState.FAILED,
    },
    TransactionState.INVENTORY_COMMITTED: {
        TransactionState.COMPLETED,
        TransactionState.FAILED,
    },
    TransactionState.COMPLETED: set(),
    TransactionState.EXPIRED: set(),
    TransactionState.RELEASED: set(),
    TransactionState.FAILED: set(),
}

class TransactionStateMachine:
    def __init__(self, initial_state: TransactionState = TransactionState.PROPOSED):
        self._state = initial_state

    @property
    def state(self) -> TransactionState:
        return self._state

    def can_transition(self, target_state: TransactionState) -> bool:
        return target_state in _ALLOWED_TRANSITIONS[self._state]

    def transition(self, target_state: TransactionState) -> TransactionState:
        if not self.can_transition(target_state):
            raise TransactionStateError(self._state, target_state)

        self._state = target_state
        return self._state