from threading import Lock
from app.core.transaction import TransactionState, TransactionStateError, _ALLOWED_TRANSITIONS
from app.models.transaction import Transaction, TransactionEvent

class TransactionNotFoundError(Exception):
    pass

class TransactionConflictError(Exception):
    pass

class TransactionStore:
    def __init__(self):
        self._transactions: dict[str, Transaction] = {}
        self._events: dict[str, list[TransactionEvent]] = {}
        self._lock = Lock()

    def create(self, transaction: Transaction) -> Transaction:
        with self._lock:
            existing = self._transactions.get(transaction.transaction_id)
            if existing is not None:
                if existing != transaction:
                    raise TransactionConflictError(
                        "Transaction already exists with different data."
                    )
                return existing
            self._transactions[transaction.transaction_id] = transaction
            self._events[transaction.transaction_id] = []
            return transaction

    def get(self, transaction_id: str) -> Transaction:
        with self._lock:
            transaction = self._transactions.get(transaction_id)
            if transaction is None:
                raise TransactionNotFoundError(transaction_id)
            return transaction

    def update(self, transaction: Transaction) -> Transaction:
        with self._lock:
            if transaction.transaction_id not in self._transactions:
                raise TransactionNotFoundError(transaction.transaction_id)
            self._transactions[transaction.transaction_id] = transaction
            return transaction

    def update_state(
        self,
        transaction_id: str,
        target_state: TransactionState,
        *,
        timestamp: int,
        reason: str | None = None,
        metadata: dict | None = None,
    ) -> Transaction:
        with self._lock:
            transaction = self._transactions.get(transaction_id)
            if transaction is None:
                raise TransactionNotFoundError(transaction_id)
            current_state = transaction.state

            if target_state not in _ALLOWED_TRANSITIONS[current_state]:
                raise TransactionStateError(current_state, target_state)

            updated_transaction = transaction.model_copy(
                update={
                    "state": target_state,
                    "updated_at": timestamp,
                }
            )

            self._transactions[transaction_id] = updated_transaction
            self._events[transaction_id].append(
                TransactionEvent(
                    transaction_id=transaction_id,
                    event_type="STATE_CHANGED",
                    timestamp=timestamp,
                    from_state=current_state,
                    to_state=target_state,
                    reason=reason,
                    metadata=metadata or {},
                )
            )
            return updated_transaction

    def add_event(self, event: TransactionEvent) -> None:
        with self._lock:
            if event.transaction_id not in self._transactions:
                raise TransactionNotFoundError(event.transaction_id)
            self._events[event.transaction_id].append(event)

    def get_events(self, transaction_id: str) -> list[TransactionEvent]:
        with self._lock:
            if transaction_id not in self._transactions:
                raise TransactionNotFoundError(transaction_id)
            return list(self._events[transaction_id])

    def clear(self) -> None:
        with self._lock:
            self._transactions.clear()
            self._events.clear()

transaction_store = TransactionStore()