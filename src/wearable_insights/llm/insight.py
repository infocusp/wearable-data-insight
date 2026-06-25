"""Public entry point for the LLM insight generation step (FR-011, FR-012).

Single public function::

    from wearable_insights.llm.insight import generate_insights

    insight_set = generate_insights(comparison)

Contract:
- Input:  a fully-populated ``ComparisonObject`` (output of the deterministic layers)
- Output: a schema-valid ``InsightSet`` with the canonical disclaimer from config

The function does NOT run the safety gate — that is the caller's responsibility
(see ``pipeline.run_pipeline`` which wraps this call with ``safety.check_insight_set``).
"""

from __future__ import annotations

from ..config import DISCLAIMER
from ..models import ComparisonObject, InsightSet
from .client import call_insight_api


def generate_insights(
    comparison: ComparisonObject,
    model: str | None = None,
) -> InsightSet:
    """Generate an InsightSet for *comparison* via the configured LLM provider.

    Args:
        comparison: Pre-computed ComparisonObject from the deterministic pipeline.
        model:      Model ID (see ``config.MODEL_OPTIONS``); defaults to
                    ``config.WEARABLE_MODEL`` (currently ``gemini-2.5-flash``).

    Returns:
        An ``InsightSet`` ready for safety validation.

    Raises:
        RuntimeError: if the required API key is not set.
        ValueError:   if *model* is not in ``MODEL_OPTIONS``.
        pydantic.ValidationError: if the model response does not conform to InsightSet.
    """
    raw = call_insight_api(comparison, model=model)

    # Pin the disclaimer to the canonical config constant — the model may paraphrase.
    return raw.model_copy(update={"disclaimer": DISCLAIMER})
