from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.models.mandate import Mandate

class CartItem(BaseModel):
    """
    One product requested by the buyer agent.
    """
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(
        min_length=1,
        description="Merchant product identifier.",
    )

    quantity: int = Field(
        gt=0,
        description="Number of units requested.",
    )


class PurchaseProposal(BaseModel):
    """
    Purchase proposal submitted by an external buyer agent.

    IMPORTANT:
    requested_unit_price is only an agent proposal.
    It is never treated as an authorized merchant price.
    """
    model_config = ConfigDict(extra="forbid")

    transaction_id: str = Field(
        min_length=1,
        description="Unique identifier for the attempted transaction.",
    )

    merchant_id: str = Field(
        min_length=1,
        description="Merchant the proposal targets.",
    )

    items: list[CartItem] = Field(
        min_length=1,
        description="Requested products.",
    )

    requested_unit_price: int = Field(
        gt=0,
        description=(
            "Price proposed by the buyer agent. "
            "This is a proposal, NOT an authorized price."
        ),
    )

    category: str = Field(
        min_length=1,
        description="Semantic product category.",
    )

    region: str = Field(
        min_length=2,
        max_length=10,
        description="Requested delivery region.",
    )

    mandate: Mandate

    @field_validator("region")
    @classmethod
    def normalize_region(cls, value: str) -> str:
        return value.upper()

    @field_validator("category")
    @classmethod
    def normalize_category(cls, value: str) -> str:
        return value.lower()