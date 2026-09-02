from enum import Enum
from pydantic import BaseModel, ConfigDict, Field

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

class Transaction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transaction_id: str = Field(min_length=1)
    merchant_id: str = Field(min_length=1)
    state: TransactionState = TransactionState.PROPOSED
    created_at: int = Field(gt=0)
    updated_at: int = Field(gt=0)
    deal_id: str | None = None
    hold_token: str | None = None
    payment_id: str | None = None
    receipt_id: str | None = None

class TransactionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transaction_id: str
    event_type: str
    timestamp: int
    from_state: TransactionState | None = None
    to_state: TransactionState | None = None
    reason: str | None = None
    metadata: dict = Field(default_factory=dict)