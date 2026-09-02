import secrets
import time
from dataclasses import dataclass
from threading import Lock

class InventoryError(Exception):
    """
    Base exception for inventory-related failures.
    """

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

@dataclass
class InventoryItem:
    """
    Current inventory state for one SKU.
    """
    sku: str
    available_quantity: int

@dataclass
class InventoryHold:
    """
    Temporary reservation of inventory.

    A hold is valid only until expires_at and while its state is HELD.
    """
    hold_token: str
    transaction_id: str
    sku: str
    quantity: int
    created_at: int
    expires_at: int
    state: str

class InMemoryInventory:
    """
    Thread-safe in-memory inventory and hold manager.

    This implementation is intentionally simple so the complete
    AMPP flow can run locally without Redis.

    Redis will later implement the same logical operations.
    """

    def __init__(
        self,
        initial_inventory: dict[str, int] | None = None,
        hold_ttl_seconds: int = 60,
    ):
        self.hold_ttl_seconds = hold_ttl_seconds
        self._inventory: dict[str, InventoryItem] = {}
        self._holds: dict[str, InventoryHold] = {}
        self._lock = Lock()

        for sku, quantity in (initial_inventory or {}).items():
            self._inventory[sku] = InventoryItem(
                sku=sku,
                available_quantity=quantity,
            )

    # Internal helpers
    def _expire_hold_if_needed(
        self,
        hold: InventoryHold,
    ) -> None:
        """
        Transition an expired HELD reservation to EXPIRED and return
        its inventory to the available pool.
        """
        now = int(time.time())

        if (
            hold.state == "HELD"
            and now >= hold.expires_at
        ):
            hold.state = "EXPIRED"
            inventory = self._inventory[hold.sku]
            inventory.available_quantity += hold.quantity

    # Inventory inspection
    def get_available_quantity(
        self,
        sku: str,
    ) -> int:
        """
        Return currently available quantity for a SKU.
        """

        with self._lock:
            item = self._inventory.get(sku)
            if item is None:
                raise InventoryError(
                    "SKU_NOT_FOUND",
                    f"SKU '{sku}' does not exist in inventory.",
                )
            self._expire_all_holds()
            return item.available_quantity

    # Hold creation
    def create_hold(
        self,
        *,
        transaction_id: str,
        sku: str,
        quantity: int,
    ) -> InventoryHold:
        """
        Atomically reserve inventory for a transaction.

        The returned hold is valid for hold_ttl_seconds.
        """

        if quantity <= 0:
            raise InventoryError(
                "INVALID_QUANTITY",
                "Hold quantity must be greater than zero.",
            )

        with self._lock:
            self._expire_all_holds()
            inventory = self._inventory.get(sku)
            if inventory is None:
                raise InventoryError(
                    "SKU_NOT_FOUND",
                    f"SKU '{sku}' does not exist in inventory.",
                )
            if inventory.available_quantity < quantity:
                raise InventoryError(
                    "INSUFFICIENT_INVENTORY",
                    (
                        f"Requested {quantity} units of '{sku}', "
                        f"but only {inventory.available_quantity} "
                        "are available."
                    ),
                )
            inventory.available_quantity -= quantity
            now = int(time.time())
            hold = InventoryHold(
                hold_token=secrets.token_urlsafe(32),
                transaction_id=transaction_id,
                sku=sku,
                quantity=quantity,
                created_at=now,
                expires_at=now + self.hold_ttl_seconds,
                state="HELD",
            )
            self._holds[hold.hold_token] = hold
            return hold

    # Hold lookup
    def get_hold(
        self,
        hold_token: str,
    ) -> InventoryHold:
        """
        Retrieve a hold and automatically expire it if necessary.
        """

        with self._lock:
            hold = self._holds.get(hold_token)
            if hold is None:
                raise InventoryError(
                    "HOLD_NOT_FOUND",
                    "Inventory hold does not exist.",
                )
            self._expire_hold_if_needed(hold)
            return hold

    # Commit
    def commit_hold(
        self,
        hold_token: str,
    ) -> InventoryHold:
        """
        Permanently commit a HELD reservation.

        Once committed, the inventory is no longer returned to
        the available pool.
        """

        with self._lock:
            hold = self._holds.get(hold_token)
            if hold is None:
                raise InventoryError(
                    "HOLD_NOT_FOUND",
                    "Inventory hold does not exist.",
                )
            self._expire_hold_if_needed(hold)
            if hold.state == "EXPIRED":
                raise InventoryError(
                    "HOLD_EXPIRED",
                    "Inventory hold has expired.",
                )
            if hold.state == "COMMITTED":
                raise InventoryError(
                    "HOLD_ALREADY_COMMITTED",
                    "Inventory hold has already been committed.",
                )
            if hold.state != "HELD":
                raise InventoryError(
                    "INVALID_HOLD_STATE",
                    (
                        f"Cannot commit hold in state "
                        f"'{hold.state}'."
                    ),
                )
            hold.state = "COMMITTED"
            return hold

    # Release
    def release_hold(
        self,
        hold_token: str,
    ) -> InventoryHold:
        """
        Explicitly release a HELD reservation.

        This is used when negotiation fails, payment fails, or the
        transaction is cancelled.
        """

        with self._lock:
            hold = self._holds.get(hold_token)
            if hold is None:
                raise InventoryError(
                    "HOLD_NOT_FOUND",
                    "Inventory hold does not exist.",
                )
            self._expire_hold_if_needed(hold)
            if hold.state == "EXPIRED":
                return hold
            if hold.state == "COMMITTED":
                raise InventoryError(
                    "HOLD_ALREADY_COMMITTED",
                    "Committed inventory cannot be released.",
                )
            if hold.state != "HELD":
                raise InventoryError(
                    "INVALID_HOLD_STATE",
                    (
                        f"Cannot release hold in state "
                        f"'{hold.state}'."
                    ),
                )
            
            inventory = self._inventory[hold.sku]
            inventory.available_quantity += hold.quantity
            hold.state = "RELEASED"
            return hold

    # Expiration
    def _expire_all_holds(self) -> None:
        """
        Expire every stale HELD reservation.

        This is acceptable for the local implementation.

        The eventual Redis implementation will use TTLs so we don't
        need to scan every hold.
        """
        
        for hold in self._holds.values():
            self._expire_hold_if_needed(hold)