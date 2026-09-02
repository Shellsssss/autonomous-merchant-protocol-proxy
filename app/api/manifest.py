from fastapi import APIRouter
from app.config import get_settings
from app.core.policy import PRODUCT_CATALOG

router = APIRouter()

@router.get(
    "/.well-known/agent-manifest.json",
    summary="Agent-readable merchant discovery manifest",
)
async def get_agent_manifest():
    """
    Return the machine-readable capabilities of this merchant.

    This endpoint is intentionally designed for AI agents rather than
    human browser clients.
    """

    settings = get_settings()
    products = []

    for product in PRODUCT_CATALOG.values():
        products.append(
            {
                "sku": product.sku,
                "name": product.name,
                "category": product.category,
                "base_price": product.base_price,
                "currency": settings.currency,
                "max_discount_percent": product.max_discount_percent,
                "min_quantity": product.min_quantity,
                "max_quantity": product.max_quantity,
                "allowed_regions": list(product.allowed_regions),
            }
        )

    return {
        "protocol": {
            "name": "AMPP",
            "version": "0.1.0",
            "role": "merchant",
        },
        "merchant": {
            "id": settings.merchant_id,
            "name": settings.merchant_name,
            "currency": settings.currency,
            "region": settings.region,
        },
        "capabilities": {
            "discovery": True,
            "semantic_catalog": True,
            "bounded_negotiation": True,
            "cryptographic_delegation": True,
            "http_402": True,
        },
        "settlement": {
            "supported": True,
            "rails": [
                "razorpay_test",
                "x402",
            ],
        },
        "constraints": {
            "inventory_hold_seconds": settings.inventory_hold_seconds,
            "clock_skew_seconds": settings.clock_skew_seconds,
        },
        "endpoints": {
            "manifest": "/.well-known/agent-manifest.json",
            "negotiate": "/api/v1/agent/negotiate",
            "settle": "/api/v1/agent/settle",
        },
        "products": products,
    }