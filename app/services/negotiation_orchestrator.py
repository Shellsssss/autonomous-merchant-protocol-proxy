from dataclasses import dataclass
from app.services.llm_negotiator import (
    LLMNegotiator,
    LLMSuggestion,
)
from app.services.negotiator import (
    BoundedNegotiator,
    NegotiationRequest,
    NegotiationResult,
)

@dataclass(frozen=True)
class OrchestrationResult:
    """
    Final result of an LLM-assisted negotiation.

    The LLM suggestion is retained for observability, but the
    deterministic negotiation result is authoritative.
    """
    suggestion: LLMSuggestion
    decision: NegotiationResult

class NegotiationOrchestrator:
    """
    Safely connects the LLM negotiation layer with the
    deterministic merchant policy layer.

    Security boundary:

        LLM output
             ↓
        structured suggestion
             ↓
        deterministic validation
             ↓
        final decision
    """

    def __init__(
        self,
        llm_negotiator: LLMNegotiator,
        bounded_negotiator: BoundedNegotiator,
    ):
        self.llm_negotiator = llm_negotiator
        self.bounded_negotiator = bounded_negotiator

    def negotiate(
        self,
        request: NegotiationRequest,
    ) -> OrchestrationResult:
        """
        Generate an LLM suggestion and independently validate it.

        The original buyer request is NOT automatically accepted.
        The LLM must produce a suggestion, which is then treated as
        untrusted input.
        """
        suggestion = self.llm_negotiator.suggest(
            request,
        )

        suggested_request = NegotiationRequest(
            sku=request.sku,
            category=request.category,
            quantity=suggestion.quantity,
            region=request.region,
            requested_unit_price=(
                suggestion.requested_unit_price
            ),
        )

        decision = self.bounded_negotiator.evaluate(
            suggested_request,
        )

        return OrchestrationResult(
            suggestion=suggestion,
            decision=decision,
        )