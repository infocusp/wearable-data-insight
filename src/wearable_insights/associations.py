"""Non-causal co-occurrence rules → CandidateAssociation list (FR-010).

Three rules are defined (data-model.md):

  R1  sleep ↓  &  stress ↑   → poor_sleep_and_higher_stress_co_occur
  R2  steps ↓  &  sleep ↓    → lower_activity_and_lower_sleep_co_occur
  R3  hrv   ↓  &  stress ↑   → reduced_recovery_and_higher_stress_co_occur

Rules are data-driven: each entry in _RULES is a declarative dict, so adding a
new rule is a one-liner with no changes to the engine.

Every generated association carries ``kind = "association"`` (never causation).
"""

from __future__ import annotations

from typing import Any

from .models import CandidateAssociation, ComparisonObject


# ── Rule table ────────────────────────────────────────────────────────────────

# Each rule is:
#   conditions: list of (section_key, metric_name, expected_trend)
#   relation:   stable string id
#   signals:    metric names involved
#   description: human-readable, association-framed text (never causal)

_RULES: list[dict[str, Any]] = [
    {
        "id": "R1",
        "conditions": [
            ("sleep", "sleep_duration", "down"),
            ("heart_health", "stress", "up"),
        ],
        "relation": "poor_sleep_and_higher_stress_co_occur",
        "signals": ["sleep_duration", "stress"],
        "description": (
            "Lower-than-usual sleep and higher-than-usual stress appear to be "
            "co-occurring today; these two patterns are often associated and may "
            "be influencing each other."
        ),
    },
    {
        "id": "R2",
        "conditions": [
            ("activity", "steps", "down"),
            ("sleep", "sleep_duration", "down"),
        ],
        "relation": "lower_activity_and_lower_sleep_co_occur",
        "signals": ["steps", "sleep_duration"],
        "description": (
            "Both your activity level and sleep are below your usual baseline today; "
            "reduced movement and shorter sleep are often associated with each other."
        ),
    },
    {
        "id": "R3",
        "conditions": [
            ("heart_health", "hrv", "down"),
            ("heart_health", "stress", "up"),
        ],
        "relation": "reduced_recovery_and_higher_stress_co_occur",
        "signals": ["hrv", "stress"],
        "description": (
            "Lower-than-usual heart rate variability and elevated stress appear to "
            "co-occur today; both may reflect a similar underlying recovery state."
        ),
    },
]


# ── Internal helpers ──────────────────────────────────────────────────────────


def _section(comparison: ComparisonObject, section_key: str) -> dict:
    return getattr(comparison, section_key, {})


def _trend(comparison: ComparisonObject, section_key: str, metric_name: str) -> str | None:
    section = _section(comparison, section_key)
    mc = section.get(metric_name)
    return mc.monthly.trend if mc is not None else None


def _rule_fires(comparison: ComparisonObject, rule: dict[str, Any]) -> bool:
    return all(
        _trend(comparison, section_key, metric_name) == expected_trend
        for section_key, metric_name, expected_trend in rule["conditions"]
    )


# ── Public API ────────────────────────────────────────────────────────────────


def compute_associations(comparison: ComparisonObject) -> list[CandidateAssociation]:
    """Evaluate all defined rules against *comparison* and return fired associations.

    Rules that do not match return nothing; the result may be an empty list.
    The order of associations mirrors the rule table order for determinism.
    """
    return [
        CandidateAssociation(
            relation=rule["relation"],
            signals=rule["signals"],
            description=rule["description"],
            kind="association",
        )
        for rule in _RULES
        if _rule_fires(comparison, rule)
    ]
