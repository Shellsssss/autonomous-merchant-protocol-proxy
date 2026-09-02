from pydantic import BaseModel, ConfigDict, Field, field_validator

class SpendingConstraints(BaseModel):
    """
    Hard limits imposed by the human on the buyer agent.
    """
    model_config = ConfigDict(extra="forbid")

    max_spend: int = Field(
        gt=0,
        description="Maximum amount the agent may spend.",
    )

    currency: str = Field(
        min_length=3,
        max_length=3,
        description="ISO-style currency code.",
    )

    allowed_categories: list[str] = Field(
        default_factory=list,
        description="Merchant categories the agent is authorized to purchase from.",
    )

    max_quantity: int = Field(
        default=1,
        gt=0,
        description="Maximum total quantity the agent may purchase.",
    )

class Mandate(BaseModel):
    """
    Cryptographically signed human delegation mandate.

    The signature covers every field except `signature`.
    """

    model_config = ConfigDict(extra="forbid")

    mandate_id: str = Field(
        min_length=1,
        description="Unique identifier for this delegation mandate.",
    )

    subject: str = Field(
        min_length=1,
        description="Identifier of the delegated buyer agent.",
    )

    merchant_id: str = Field(
        min_length=1,
        description="Merchant this mandate authorizes.",
    )

    constraints: SpendingConstraints

    issued_at: int = Field(
        gt=0,
        description="Unix timestamp when the mandate was issued.",
    )

    expires_at: int = Field(
        gt=0,
        description="Unix timestamp when the mandate expires.",
    )

    nonce: str = Field(
        min_length=16,
        description="Unique value preventing mandate replay.",
    )

    public_key: str = Field(
        min_length=1,
        description="Base64-encoded Ed25519 public key.",
    )

    signature: str = Field(
        min_length=1,
        description="Base64-encoded Ed25519 signature.",
    )

    @field_validator("expires_at")
    @classmethod
    def expiry_must_follow_issue_time(cls, value: int, info):
        issued_at = info.data.get("issued_at")
        if issued_at is not None and value <= issued_at:
            raise ValueError("expires_at must be greater than issued_at")
        return value