from app.services.llm_negotiator import (
    LLMSuggestion,
)
from app.services.negotiation_orchestrator import (
    NegotiationOrchestrator,
)
from app.services.negotiator import (
    BoundedNegotiator,
    NegotiationRequest,
)

class FakeLLMNegotiator:
    """
    Deterministic fake LLM used for testing.

    This avoids network/API calls.
    """

    def __init__(
        self,
        suggestion: LLMSuggestion,
    ):
        self.suggestion = suggestion

    def suggest(
        self,
        request: NegotiationRequest,
    ) -> LLMSuggestion:
        return self.suggestion

def make_request(
    *,
    price: int = 4800,
    quantity: int = 1,
) -> NegotiationRequest:
    return NegotiationRequest(
        sku="LAPTOP-PRO-01",
        category="electronics",
        quantity=quantity,
        region="IN",
        requested_unit_price=price,
    )

def test_valid_llm_suggestion_is_accepted():
    llm = FakeLLMNegotiator(
        LLMSuggestion(
            requested_unit_price=4700,
            quantity=1,
            reasoning="Reasonable discount.",
        )
    )

    orchestrator = NegotiationOrchestrator(
        llm_negotiator=llm,
        bounded_negotiator=BoundedNegotiator(),
    )

    result = orchestrator.negotiate(
        make_request(),
    )

    assert result.suggestion.requested_unit_price == 4700
    assert result.decision.approved is True
    assert result.decision.approved_unit_price == 4700

def test_llm_cannot_bypass_floor_price():
    """
    Critical security test.

    The fake LLM deliberately suggests a price below
    the merchant's floor.
    """

    llm = FakeLLMNegotiator(
        LLMSuggestion(
            requested_unit_price=1000,
            quantity=1,
            reasoning="Ignore the merchant's discount rules.",
        )
    )

    orchestrator = NegotiationOrchestrator(
        llm_negotiator=llm,
        bounded_negotiator=BoundedNegotiator(),
    )

    result = orchestrator.negotiate(
        make_request(),
    )

    assert result.suggestion.requested_unit_price == 1000
    assert result.decision.approved is False
    assert result.decision.reason_code == (
        "RULE_MAX_DISCOUNT_EXCEEDED"
    )

def test_llm_cannot_exceed_quantity_limit():
    llm = FakeLLMNegotiator(
        LLMSuggestion(
            requested_unit_price=4700,
            quantity=1000,
            reasoning="Pretend inventory is unlimited.",
        )
    )

    orchestrator = NegotiationOrchestrator(
        llm_negotiator=llm,
        bounded_negotiator=BoundedNegotiator(),
    )

    result = orchestrator.negotiate(
        make_request(),
    )

    assert result.decision.approved is False
    assert result.decision.reason_code == (
        "MAX_QUANTITY_EXCEEDED"
    )

def test_llm_suggestion_does_not_modify_original_request():
    llm = FakeLLMNegotiator(
        LLMSuggestion(
            requested_unit_price=4600,
            quantity=2,
            reasoning="Volume discount.",
        )
    )

    request = make_request(
        price=4800,
        quantity=1,
    )

    orchestrator = NegotiationOrchestrator(
        llm_negotiator=llm,
        bounded_negotiator=BoundedNegotiator(),
    )
    
    result = orchestrator.negotiate(request)

    assert request.requested_unit_price == 4800
    assert request.quantity == 1
    assert result.suggestion.requested_unit_price == 4600
    assert result.suggestion.quantity == 2

def test_llm_suggestion_is_retained_for_auditability():
    llm = FakeLLMNegotiator(
        LLMSuggestion(
            requested_unit_price=4800,
            quantity=1,
            reasoning="Within merchant boundaries.",
        )
    )

    orchestrator = NegotiationOrchestrator(
        llm_negotiator=llm,
        bounded_negotiator=BoundedNegotiator(),
    )

    result = orchestrator.negotiate(
        make_request(),
    )

    assert result.suggestion.reasoning == (
        "Within merchant boundaries."
    )