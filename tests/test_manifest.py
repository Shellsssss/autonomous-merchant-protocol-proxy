from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_agent_manifest_is_available():
    response = client.get(
        "/.well-known/agent-manifest.json"
    )
    assert response.status_code == 200

def test_agent_manifest_contains_protocol():
    response = client.get(
        "/.well-known/agent-manifest.json"
    )
    data = response.json()
    assert data["protocol"]["name"] == "AMPP"
    assert data["protocol"]["role"] == "merchant"

def test_agent_manifest_contains_merchant():
    response = client.get(
        "/.well-known/agent-manifest.json"
    )
    data = response.json()
    assert data["merchant"]["id"] == "merchant_demo_01"
    assert data["merchant"]["currency"] == "INR"

def test_agent_manifest_contains_settlement_rails():
    response = client.get(
        "/.well-known/agent-manifest.json"
    )
    data = response.json()
    assert "razorpay_test" in data["settlement"]["rails"]
    assert "x402" in data["settlement"]["rails"]

def test_agent_manifest_contains_products():
    response = client.get(
        "/.well-known/agent-manifest.json"
    )
    data = response.json()
    assert len(data["products"]) > 0
    
    product = data["products"][0]
    assert "sku" in product
    assert "base_price" in product
    assert "category" in product
    assert "max_discount_percent" in product