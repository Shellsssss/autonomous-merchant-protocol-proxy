from enum import Enum

class TransactionState(str, Enum):
    """
    Lifecycle states for an AMPP transaction.
    """
    PROPOSED = "PROPOSED"
    VALIDATED = "VALIDATED"
    HELD = "HELD"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    SETTLED = "SETTLED"
    EXPIRED = "EXPIRED"
    RELEASED = "RELEASED"
    FAILED = "FAILED"

class TransactionStateError(Exception):
    """
    Raised when an invalid transaction state transition is attempted.
    """

    def __init__(
        self,
        current_state: TransactionState,
        requested_state: TransactionState,
    ):
        self.current_state = current_state
        self.requested_state = requested_state

        super().__init__(
            (
                f"Invalid transaction transition: "
                f"{current_state.value} -> "
                f"{requested_state.value}"
            )
        )

# Allowed transitions
_ALLOWED_TRANSITIONS: dict[
    TransactionState,
    set[TransactionState],
] = {
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
        TransactionState.SETTLED,
        TransactionState.EXPIRED,
        TransactionState.FAILED,
    },

    TransactionState.SETTLED: set(),
    TransactionState.EXPIRED: set(),
    TransactionState.RELEASED: set(),
    TransactionState.FAILED: set(),
}

class TransactionStateMachine:
    """
    Deterministic state machine for an AMPP transaction.

    Every state transition is explicitly validated.

    This prevents payment or fulfillment code from accidentally
    operating on an invalid transaction state.
    """

    def __init__(
        self,
        initial_state: TransactionState = TransactionState.PROPOSED,
    ):
        self._state = initial_state

    @property
    def state(self) -> TransactionState:
        """
        Return the current transaction state.
        """
        return self._state

    def can_transition(
        self,
        target_state: TransactionState,
    ) -> bool:
        """
        Check whether a transition is allowed without mutating state.
        """
        return target_state in _ALLOWED_TRANSITIONS[
            self._state
        ]

    def transition(
        self,
        target_state: TransactionState,
    ) -> TransactionState:
        """
        Perform a validated state transition.
        """

        if not self.can_transition(target_state):
            raise TransactionStateError(
                current_state=self._state,
                requested_state=target_state,
            )
        self._state = target_state
        return self._state