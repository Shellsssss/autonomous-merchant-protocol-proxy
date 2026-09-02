from threading import Lock
from app.models.settlement import FulfillmentReceipt

class ReceiptConflictError(Exception):
    pass

class ReceiptNotFoundError(Exception):
    pass

class ReceiptStore:
    def __init__(self):
        self._receipts: dict[str, FulfillmentReceipt] = {}
        self._lock = Lock()

    def create(self, receipt: FulfillmentReceipt) -> FulfillmentReceipt:
        with self._lock:
            existing = self._receipts.get(receipt.receipt_id)
            if existing is not None:
                if existing != receipt:
                    raise ReceiptConflictError(
                        "Receipt already exists with different data."
                    )
                return existing
            self._receipts[receipt.receipt_id] = receipt
            return receipt

    def get(self, receipt_id: str) -> FulfillmentReceipt:
        with self._lock:
            receipt = self._receipts.get(receipt_id)
            if receipt is None:
                raise ReceiptNotFoundError(receipt_id)
            return receipt

    def clear(self) -> None:
        with self._lock:
            self._receipts.clear()

receipt_store = ReceiptStore()