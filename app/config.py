from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application configuration.

    Values are loaded from environment variables and/or a local .env file.
    """

    # Application
    app_name: str = "AMPP Merchant Proxy"
    app_version: str = "0.1.0"
    environment: str = Field(
        default="development",
        description="development | test | production",
    )
    debug: bool = True

    # Merchant
    merchant_id: str = "merchant_demo_01"
    merchant_name: str = "AMPP Demo Merchant"
    currency: str = "INR"
    region: str = "IN"

    # Inventory
    inventory_hold_seconds: int = 60

    # Security
    # How long a nonce remains in the replay-protection ledger.
    nonce_ttl_seconds: int = 120
    # Maximum acceptable clock skew for signed requests.
    clock_skew_seconds: int = 30

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Gemini
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"

    # Razorpay
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None

    # Pydantic Settings configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """
    Return a cached application configuration.

    Caching prevents repeatedly parsing environment variables and
    recreating the Settings object for every request.
    """
    return Settings()