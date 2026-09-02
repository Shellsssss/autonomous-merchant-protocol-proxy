import json
import pytest
from app.services.llm_negotiator import (
    LLMNegotiator,
    LLMSuggestion,
)

def test_valid_llm_response_is_parsed():
    response = json.dumps(
        {
            "requested_unit_price": 4700,
            "quantity": 1,
            "reasoning": "Reasonable volume-adjusted offer.",
        }
    )

    suggestion = LLMNegotiator._parse_response(
        response,
    )

    assert isinstance(
        suggestion,
        LLMSuggestion,
    )
    assert suggestion.requested_unit_price == 4700
    assert suggestion.quantity == 1
    assert suggestion.reasoning == (
        "Reasonable volume-adjusted offer."
    )

def test_llm_response_with_extra_fields_is_rejected():
    response = json.dumps(
        {
            "requested_unit_price": 4700,
            "quantity": 1,
            "reasoning": "Test.",
            "approved": True,
        }
    )

    with pytest.raises(RuntimeError):
        LLMNegotiator._parse_response(
            response,
        )

def test_invalid_json_is_rejected():
    with pytest.raises(RuntimeError):
        LLMNegotiator._parse_response(
            "this is not json",
        )

def test_non_integer_price_is_rejected():
    response = json.dumps(
        {
            "requested_unit_price": 4700.5,
            "quantity": 1,
            "reasoning": "Test.",
        }
    )

    with pytest.raises(RuntimeError):
        LLMNegotiator._parse_response(
            response,
        )

def test_non_integer_quantity_is_rejected():
    response = json.dumps(
        {
            "requested_unit_price": 4700,
            "quantity": "1",
            "reasoning": "Test.",
        }
    )

    with pytest.raises(RuntimeError):
        LLMNegotiator._parse_response(
            response,
        )

def test_zero_price_is_rejected():
    response = json.dumps(
        {
            "requested_unit_price": 0,
            "quantity": 1,
            "reasoning": "Test.",
        }
    )

    with pytest.raises(RuntimeError):
        LLMNegotiator._parse_response(
            response,
        )

def test_zero_quantity_is_rejected():
    response = json.dumps(
        {
            "requested_unit_price": 4700,
            "quantity": 0,
            "reasoning": "Test.",
        }
    )

    with pytest.raises(RuntimeError):
        LLMNegotiator._parse_response(
            response,
        )