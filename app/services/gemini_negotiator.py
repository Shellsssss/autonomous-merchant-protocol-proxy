import json

from google import genai

from app.config import get_settings


class GeminiNegotiatorError(Exception):
    pass


class GeminiNegotiator:
    def __init__(self):
        settings = get_settings()

        if not settings.gemini_api_key:
            raise GeminiNegotiatorError(
                "Gemini API key is not configured."
            )

        self.client = genai.Client(
            api_key=settings.gemini_api_key
        )
        self.model = settings.gemini_model

    def negotiate(
        self,
        *,
        sku: str,
        quantity: int,
        requested_unit_price: int,
        category: str,
        merchant_id: str,
    ) -> dict:

        prompt = f"""
You are the negotiation assistant inside an autonomous commerce system.

Your job is ONLY to suggest a commercial deal.

You MUST NOT authorize payment.
You MUST NOT override spending limits.
You MUST NOT make security or policy decisions.

Input:
{json.dumps({
    "sku": sku,
    "quantity": quantity,
    "requested_unit_price": requested_unit_price,
    "category": category,
    "merchant_id": merchant_id,
}, indent=2)}

Return ONLY valid JSON:

{{
  "decision": "ACCEPT" | "COUNTER" | "REJECT",
  "suggested_unit_price": integer,
  "reason": "short explanation"
}}

Rules:
- suggested_unit_price must be positive.
- Never invent a quantity.
- Do not claim authorization.
- Keep the response concise.
"""

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
            )
        except Exception as exc:
            print(f"[GEMINI API ERROR] {type(exc).__name__}: {exc}")
            raise GeminiNegotiatorError(
                "Gemini negotiation request failed."
            ) from exc

        text = response.text.strip()

        try:
            result = json.loads(text)
        except json.JSONDecodeError as exc:
            raise GeminiNegotiatorError(
                "Gemini returned invalid negotiation JSON."
            ) from exc

        required = {
            "decision",
            "suggested_unit_price",
            "reason",
        }

        if not required.issubset(result):
            raise GeminiNegotiatorError(
                "Gemini negotiation response is incomplete."
            )

        if result["decision"] not in {
            "ACCEPT",
            "COUNTER",
            "REJECT",
        }:
            raise GeminiNegotiatorError(
                "Gemini returned an invalid decision."
            )

        if not isinstance(result["suggested_unit_price"], int):
            raise GeminiNegotiatorError(
                "Gemini returned an invalid price."
            )

        if result["suggested_unit_price"] <= 0:
            raise GeminiNegotiatorError(
                "Gemini returned a non-positive price."
            )

        return result


gemini_negotiator = GeminiNegotiator()