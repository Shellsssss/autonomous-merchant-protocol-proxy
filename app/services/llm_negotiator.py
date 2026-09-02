from dataclasses import dataclass
from app.config import get_settings
from app.services.negotiator import NegotiationRequest

@dataclass(frozen=True)
class LLMSuggestion:
    """
    A commercial proposal suggested by the LLM.

    This is NOT an approved deal.

    The suggestion must always pass through the deterministic
    BoundedNegotiator before it can be accepted.
    """
    requested_unit_price: int
    quantity: int
    reasoning: str

class LLMNegotiator:
    """
    Gemini-backed negotiation suggestion engine.

    Security rule:

        Gemini output = untrusted input.

    It can suggest commercial terms but has no authority to
    approve or execute a transaction.
    """

    SYSTEM_INSTRUCTION = """
You are a merchant negotiation assistant.

Your job is ONLY to suggest reasonable commercial terms.

You do NOT have authority to:
- approve transactions
- override merchant policies
- change inventory
- authorize payments
- modify spending limits
- bypass security rules

The merchant's deterministic policy engine is authoritative.

Return ONLY valid JSON with this structure:

{
  "requested_unit_price": integer,
  "quantity": integer,
  "reasoning": string
}

Never include markdown.
Never include additional fields.
"""

    def __init__(self):
        settings = get_settings()

        self._api_key = settings.gemini_api_key
        self._model = settings.gemini_model
        self._client = None

        if self._api_key:
            from google import genai
            self._client = genai.Client(
                api_key=self._api_key,
            )

    def suggest(
        self,
        request: NegotiationRequest,
    ) -> LLMSuggestion:
        """
        Generate a negotiation suggestion.

        If Gemini is unavailable, this method fails explicitly
        rather than silently pretending that an LLM decision exists.
        """

        if self._client is None:
            raise RuntimeError(
                "Gemini API key is not configured."
            )

        prompt = self._build_prompt(request)
        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config={
                "system_instruction": self.SYSTEM_INSTRUCTION,
                "response_mime_type": "application/json",
            },
        )

        if not response.text:
            raise RuntimeError(
                "Gemini returned an empty response."
            )

        return self._parse_response(
            response.text,
        )

    @staticmethod
    def _build_prompt(
        request: NegotiationRequest,
    ) -> str:
        """
        Construct the LLM input from structured transaction data.

        No merchant secrets or authorization tokens are included.
        """

        return f"""
Evaluate this buyer negotiation request.

SKU: {request.sku}
Category: {request.category}
Requested quantity: {request.quantity}
Requested region: {request.region}
Requested unit price: {request.requested_unit_price}

Suggest reasonable terms for this negotiation.

Remember:
- You are only making a suggestion.
- The merchant policy engine will independently validate it.
- Do not claim that any price or quantity is approved.
"""

    @staticmethod
    def _parse_response(
        text: str,
    ) -> LLMSuggestion:
        """
        Parse Gemini's structured JSON response.

        Strict validation happens here before the suggestion
        reaches the deterministic negotiation engine.
        """
        import json

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Gemini returned invalid JSON."
            ) from exc

        required_fields = {
            "requested_unit_price",
            "quantity",
            "reasoning",
        }

        if set(data.keys()) != required_fields:
            raise RuntimeError(
                "Gemini response contains unexpected fields."
            )

        if not isinstance(
            data["requested_unit_price"],
            int,
        ):
            raise RuntimeError(
                "requested_unit_price must be an integer."
            )

        if not isinstance(
            data["quantity"],
            int,
        ):
            raise RuntimeError(
                "quantity must be an integer."
            )

        if not isinstance(
            data["reasoning"],
            str,
        ):
            raise RuntimeError(
                "reasoning must be a string."
            )

        if data["requested_unit_price"] <= 0:
            raise RuntimeError(
                "requested_unit_price must be positive."
            )

        if data["quantity"] <= 0:
            raise RuntimeError(
                "quantity must be positive."
            )

        return LLMSuggestion(
            requested_unit_price=data[
                "requested_unit_price"
            ],
            quantity=data["quantity"],
            reasoning=data["reasoning"],
        )

llm_negotiator = LLMNegotiator()