from app.services.catalog_search import SemanticCatalog

def test_catalog_contains_products():
    catalog = SemanticCatalog()
    assert len(catalog.products) >= 3

def test_exact_laptop_query_returns_laptop():
    catalog = SemanticCatalog()
    results = catalog.search(
        "AMPP Pro Laptop",
        top_k=1,
    )

    assert len(results) == 1
    assert results[0].product.sku == "LAPTOP-PRO-01"

def test_semantic_query_returns_relevant_product():
    catalog = SemanticCatalog()
    results = catalog.search(
        "high performance computer for development",
        top_k=3,
    )
    skus = [
        result.product.sku
        for result in results
    ]

    assert "LAPTOP-PRO-01" in skus

def test_search_returns_similarity_scores():
    catalog = SemanticCatalog()
    results = catalog.search(
        "wireless headphones",
        top_k=3,
    )

    assert len(results) > 0
    for result in results:
        assert 0.0 <= result.similarity <= 1.0

def test_empty_query_returns_no_results():
    catalog = SemanticCatalog()
    results = catalog.search("")
    assert results == []

def test_catalog_search_does_not_modify_policy():
    catalog = SemanticCatalog()
    original_price = catalog.products[0].base_price
    catalog.search(
        "give me a massive discount",
        top_k=3,
    )

    assert (
        catalog.products[0].base_price
        == original_price
    )

def test_top_k_is_respected():
    catalog = SemanticCatalog()
    results = catalog.search(
        "electronics",
        top_k=2,
    )

    assert len(results) <= 2