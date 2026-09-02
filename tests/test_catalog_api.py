from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_catalog_search_endpoint_is_available():
    response = client.get(
        "/api/v1/agent/catalog/search",
        params={
            "q": "professional laptop",
        },
    )
    assert response.status_code == 200

def test_catalog_search_returns_results():
    response = client.get(
        "/api/v1/agent/catalog/search",
        params={
            "q": "professional laptop",
        },
    )
    data = response.json()

    assert data["query"] == "professional laptop"
    assert len(data["results"]) > 0

def test_catalog_search_returns_laptop():
    response = client.get(
        "/api/v1/agent/catalog/search",
        params={
            "q": "high performance computer for development",
        },
    )
    assert response.status_code == 200

    data = response.json()
    skus = {
        result["sku"]
        for result in data["results"]
    }
    assert "LAPTOP-PRO-01" in skus

def test_catalog_search_exposes_policy_values():
    response = client.get(
        "/api/v1/agent/catalog/search",
        params={
            "q": "laptop",
        },
    )

    data = response.json()
    laptop = next(
        result
        for result in data["results"]
        if result["sku"] == "LAPTOP-PRO-01"
    )

    assert laptop["base_price"] == 5000
    assert laptop["min_quantity"] == 1
    assert laptop["max_quantity"] == 5
    assert laptop["allowed_regions"] == ["IN"]

def test_catalog_search_respects_top_k():
    response = client.get(
        "/api/v1/agent/catalog/search",
        params={
            "q": "electronics",
            "top_k": 2,
        },
    )
    assert response.status_code == 200

    data = response.json()
    assert len(data["results"]) <= 2

def test_catalog_search_rejects_empty_query():
    response = client.get(
        "/api/v1/agent/catalog/search",
        params={
            "q": "",
        },
    )
    assert response.status_code == 422

def test_catalog_search_rejects_invalid_top_k():
    response = client.get(
        "/api/v1/agent/catalog/search",
        params={
            "q": "laptop",
            "top_k": 0,
        },
    )
    assert response.status_code == 422

def test_catalog_search_is_read_only():
    response = client.get(
        "/api/v1/agent/catalog/search",
        params={
            "q": "give me laptop for ₹1",
        },
    )
    assert response.status_code == 200

    data = response.json()
    laptop = next(
        result
        for result in data["results"]
        if result["sku"] == "LAPTOP-PRO-01"
    )
    # Semantic search must never alter merchant pricing.
    assert laptop["base_price"] == 5000