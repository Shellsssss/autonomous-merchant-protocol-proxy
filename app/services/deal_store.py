from threading import Lock
from app.models import Deal

class DealNotFoundError(Exception):
    """
    Raised when a transaction does not exist in the deal store.
    """
    def __init__(self, transaction_id: str):
        self.transaction_id = transaction_id
        super().__init__(
            f"Deal for transaction '{transaction_id}' was not found."
        )

class DealConflictError(Exception):
    """
    Raised when a transaction is reused with conflicting deal data.
    """
    def __init__(self, transaction_id: str):
        self.transaction_id = transaction_id
        super().__init__(
            f"Conflicting deal already exists for "
            f"transaction '{transaction_id}'."
        )

class DealStore:
    """
    Thread-safe in-memory store for active AMPP deals.

    The store keeps the server-side representation of a negotiated
    transaction so that later settlement requests do not need to
    trust the buyer agent to resend pricing or inventory information.

    This is intentionally in-memory for the prototype.

    Later this can be replaced by Redis/PostgreSQL without changing
    the API contract.
    """

    def __init__(self):
        self._deals: dict[str, Deal] = {}
        self._lock = Lock()

    def create(self, deal: Deal) -> Deal:
        """
        Store a newly created deal.

        A transaction_id is treated as unique.

        Re-submitting the exact same deal is idempotent and returns
        the existing deal.

        A different deal using the same transaction_id is rejected.
        """
        with self._lock:
            existing = self._deals.get(deal.transaction_id)
            if existing is not None:
                if existing == deal:
                    return existing
                raise DealConflictError(
                    deal.transaction_id
                )
            self._deals[deal.transaction_id] = deal
            return deal

    def get(self, transaction_id: str) -> Deal:
        """
        Retrieve a deal by transaction ID.
        """
        with self._lock:
            deal = self._deals.get(transaction_id)
            if deal is None:
                raise DealNotFoundError(transaction_id)
            return deal

    def update(self, deal: Deal) -> Deal:
        """
        Replace an existing deal.

        Used when the settlement lifecycle changes the deal state.
        """
        with self._lock:
            if deal.transaction_id not in self._deals:
                raise DealNotFoundError(
                    deal.transaction_id
                )
            self._deals[deal.transaction_id] = deal
            return deal

    def clear(self) -> None:
        """
        Clear all stored deals.

        Primarily useful for tests.
        """
        with self._lock:
            self._deals.clear()

# Shared application-level deal store.
deal_store = DealStore()

def get_deal(transaction_id: str) -> Deal | None:
    """
    Retrieve a negotiated deal by transaction ID.

    Returns None when no deal exists.
    """
    return deal_store.get(transaction_id)