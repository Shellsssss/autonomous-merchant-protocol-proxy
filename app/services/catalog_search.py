from dataclasses import dataclass
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from app.core.policy import PRODUCT_CATALOG, ProductPolicy

@dataclass(frozen=True)
class CatalogSearchResult:
    """
    A product returned from semantic catalog search.

    Similarity is informational only. It does NOT influence
    merchant policy decisions.
    """
    product: ProductPolicy
    similarity: float

class SemanticCatalog:
    """
    Semantic search over the merchant's product catalog.

    The catalog itself remains sourced from PRODUCT_CATALOG.
    Embeddings are only used to find relevant products.
    """
    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
    ):
        self.model = SentenceTransformer(model_name)

        self.products = list(
            PRODUCT_CATALOG.values()
        )

        self.documents = [
            self._product_document(product)
            for product in self.products
        ]

        self.embeddings = self.model.encode(
            self.documents,
            normalize_embeddings=True,
        )

    @staticmethod
    def _product_document(
        product: ProductPolicy,
    ) -> str:
        """
        Build the semantic representation of a product.

        This intentionally contains descriptive information rather
        than security-sensitive instructions.
        """
        return (
            f"{product.name}. "
            f"SKU: {product.sku}. "
            f"Category: {product.category}. "
            f"Price: {product.base_price} INR."
        )

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
    ) -> list[CatalogSearchResult]:
        """
        Return the most semantically relevant products.
        """
        if not query.strip():
            return []

        query_embedding = self.model.encode(
            [query],
            normalize_embeddings=True,
        )

        similarities = cosine_similarity(
            query_embedding,
            self.embeddings,
        )[0]

        ranked_indices = similarities.argsort()[::-1]
        results: list[CatalogSearchResult] = []

        for index in ranked_indices[:top_k]:
            results.append(
                CatalogSearchResult(
                    product=self.products[index],
                    similarity=float(
                        similarities[index]
                    ),
                )
            )

        return results

_catalog = None
def get_catalog() -> SemanticCatalog:
    """
    Lazily initialize the semantic catalog.

    Loading the embedding model is relatively expensive, so we
    don't want to initialize it on every API request.
    """
    
    global _catalog
    if _catalog is None:
        _catalog = SemanticCatalog()
    return _catalog