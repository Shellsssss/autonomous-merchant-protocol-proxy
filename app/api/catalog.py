from fastapi import APIRouter, Query
from app.services.catalog_search import get_catalog

router = APIRouter(
    prefix="/api/v1/agent/catalog",
    tags=["Agent Catalog"],
)

@router.get(
    "/search",
    summary="Semantic product search for AI agents",
)
async def search_catalog(
    q: str = Query(
        min_length=1,
        description="Natural-language product search query.",
    ),
    top_k: int = Query(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of products to return.",
    ),
):
    """
    Search the merchant catalog using natural-language semantics.

    Semantic similarity is used only for product discovery.
    Merchant prices, quantities, categories, and regions remain
    controlled by the deterministic policy engine.
    """
    catalog = get_catalog()
    results = catalog.search(
        q,
        top_k=top_k,
    )

    return {
        "query": q,
        "results": [
            {
                "sku": result.product.sku,
                "name": result.product.name,
                "category": result.product.category,
                "base_price": result.product.base_price,
                "currency": "INR",
                "min_quantity": result.product.min_quantity,
                "max_quantity": result.product.max_quantity,
                "allowed_regions": list(
                    result.product.allowed_regions
                ),
                "similarity": round(
                    result.similarity,
                    4,
                ),
            }
            for result in results
        ],
    }