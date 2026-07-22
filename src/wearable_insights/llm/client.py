"""LLM client factory — dispatches to Anthropic or Google based on model."""

from __future__ import annotations

from ..config import ANTHROPIC_API_KEY, MODEL_OPTIONS, WEARABLE_MODEL
from ..models import ComparisonObject, InsightSet
from .google_client import make_google_client
from .prompt import SYSTEM_TEXT, build_user_payload

_MAX_TOKENS = 8192


# ── Anthropic ─────────────────────────────────────────────────────────────────

def _call_anthropic(comparison: ComparisonObject, model: str) -> InsightSet:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. "
            "Export it in your environment before running the LLM pipeline."
        )
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    messages = build_user_payload(comparison)

    # Anthropic system prompt uses cache_control blocks.
    system_blocks = [
        {
            "type": "text",
            "text": SYSTEM_TEXT,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    response = client.messages.parse(
        model=model,
        max_tokens=_MAX_TOKENS,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        system=system_blocks,
        messages=messages,
        output_format=InsightSet,
    )
    return response.parsed_output


# ── Google ────────────────────────────────────────────────────────────────────

def _call_google(comparison: ComparisonObject, model: str) -> InsightSet:
    from google.genai import types

    client = make_google_client()
    user_payload = build_user_payload(comparison)
    user_text = user_payload[0]["content"]

    response = client.models.generate_content(
        model=model,
        contents=user_text,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_TEXT,
            response_mime_type="application/json",
            response_schema=InsightSet,
        ),
    )
    return InsightSet.model_validate_json(response.text)


# ── Dispatcher ────────────────────────────────────────────────────────────────

def call_insight_api(
    comparison: ComparisonObject,
    model: str | None = None,
) -> InsightSet:
    """Call the appropriate LLM provider and return a parsed InsightSet.

    Args:
        comparison: The pre-computed ComparisonObject to interpret.
        model:      Model ID from MODEL_OPTIONS; defaults to WEARABLE_MODEL.

    Raises:
        RuntimeError: if the required API key is not configured.
        ValueError:   if the model is not in MODEL_OPTIONS.
    """
    resolved = model or WEARABLE_MODEL
    info = MODEL_OPTIONS.get(resolved)
    if info is None:
        raise ValueError(
            f"Unknown model '{resolved}'. Valid options: {list(MODEL_OPTIONS)}"
        )

    provider = info["provider"]
    if provider == "anthropic":
        return _call_anthropic(comparison, resolved)
    if provider == "google":
        return _call_google(comparison, resolved)
    raise ValueError(f"Unsupported provider '{provider}' for model '{resolved}'")
