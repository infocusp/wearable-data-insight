"""Unit: deterministic underwriting signals.

The contract this surface must uphold: every number is computed in Python, higher is
always better, no decision or price is ever emitted, and a thin history is reported as
thin rather than quietly scored as if it were complete.
"""

from __future__ import annotations

from datetime import date

import pytest

from wearable_insights.data.synthetic import generate_synthetic_profile
from wearable_insights.underwriting import (
    UNDERWRITING_DISCLAIMER,
    build_underwriting_signals,
)

END = date(2026, 8, 25)


def _signals(persona: str, days: int = 90):
    profile = generate_synthetic_profile(persona, seed=42, days=days, end_date=END)
    return build_underwriting_signals(profile, END)


def test_deterministic_for_same_inputs():
    assert _signals("healthy_consistent").model_dump() == _signals(
        "healthy_consistent"
    ).model_dump()


def test_scores_are_bounded_and_directions_consistent():
    result = _signals("healthy_consistent")
    for signal in result.signals:
        assert 0 <= signal.score <= 100
        if signal.score >= 70:
            assert signal.direction == "favorable"
        elif signal.score <= 45:
            assert signal.direction == "attention"
        else:
            assert signal.direction == "neutral"


def test_consistent_persona_scores_favorably():
    result = _signals("healthy_consistent")
    assert result.composite.consistency >= 70
    assert not result.low_confidence


def test_volatility_is_the_inverse_of_consistency():
    """Volatility is the one risk-polarity tile; the UI depends on that relationship."""
    result = _signals("healthy_consistent")
    assert result.composite.volatility == 100 - result.composite.consistency


def test_consistently_inactive_does_not_score_as_favorable():
    """A sedentary member is *consistent*, but consistency alone must not read as good —
    otherwise the signal rewards stable inactivity."""
    result = _signals("low_activity")
    activity = next(s for s in result.signals if s.key == "activity_consistency")
    assert activity.direction == "attention"
    assert activity.score < 50


def test_short_history_lowers_completeness_and_flags_low_confidence():
    result = _signals("recovery_decline", days=22)
    completeness = next(s for s in result.signals if s.key == "data_completeness")
    assert result.low_confidence
    assert completeness.score < 60, "22 days of data must not present as complete evidence"
    assert any("22 days" in point for point in result.attention_points)


def test_signals_carry_provenance_and_deterministic_detail():
    for signal in _signals("healthy_consistent").signals:
        assert signal.metrics, f"{signal.key} has no provenance"
        assert signal.detail, f"{signal.key} has no explanatory detail"


def test_no_narrative_and_no_decision_language():
    """This build ships deterministic-only: no LLM prose, and never a decision or price."""
    result = _signals("healthy_consistent")
    assert result.narrative is None
    assert result.safety_profile is None

    # Scan the *content* only. The disclaimer is boilerplate that necessarily names
    # what it disclaims ("contains no diagnosis", "an underwriting decision").
    content = result.model_copy(update={"disclaimer": ""}).model_dump_json().lower()
    for forbidden in (
        "approve", "decline", "reject", "uninsurable", "deny",
        "premium", "loading", "rate up", "diagnos",
    ):
        assert forbidden not in content, f"underwriting output contained '{forbidden}'"


def test_disclaimer_states_human_review_is_required():
    result = _signals("healthy_consistent")
    assert result.disclaimer == UNDERWRITING_DISCLAIMER
    assert "not be the sole basis" in result.disclaimer
    assert "human review" in result.disclaimer.lower()
