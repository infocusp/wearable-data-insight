"""Unit tests for safety.py (FR-014, FR-015, FR-019, SC-004)."""

from __future__ import annotations

from datetime import date

import pytest

from wearable_insights.config import DISCLAIMER
from wearable_insights.models import (
    CandidateAssociation,
    ComparisonObject,
    DataQuality,
    Insight,
    InsightSet,
    MetricComparison,
)
from wearable_insights.safety import SafetyError, check_insight_set, violations


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _clean_insight(**overrides) -> Insight:
    base = dict(
        title="Good rest ahead",
        summary=(
            "Your HRV is trending lower than your usual baseline, which may be "
            "associated with how your body is recovering from recent activity. "
            "Sleep patterns appear to have shifted slightly this week."
        ),
        action="Go to bed 30 minutes earlier tonight to support your recovery.",
        confidence="medium",
        source_signals=["hrv", "sleep_duration"],
    )
    base.update(overrides)
    return Insight(**base)


def _clean_set(**overrides) -> InsightSet:
    base = dict(
        insights=[_clean_insight()],
        disclaimer=DISCLAIMER,
        generated_from=["hrv", "sleep_duration"],
        schema_version="1.0",
    )
    base.update(overrides)
    return InsightSet(**base)


def _simple_comparison() -> ComparisonObject:
    mc = MetricComparison()
    return ComparisonObject(
        user_id="u1",
        analysis_date=date(2026, 6, 17),
        sleep={"sleep_duration": mc, "sleep_score": mc, "deep_sleep": mc, "rem_sleep": mc},
        heart_health={"resting_hr": mc, "hrv": mc, "stress": mc},
        activity={"steps": mc, "active_minutes": mc},
        candidate_associations=[],
        data_quality=DataQuality(),
    )


# ── Happy path ────────────────────────────────────────────────────────────────


def test_clean_insight_passes():
    result = check_insight_set(_clean_set())
    assert isinstance(result, InsightSet)


def test_returns_original_object_on_success():
    s = _clean_set()
    assert check_insight_set(s) is s


def test_clean_insight_with_comparison_passes():
    check_insight_set(_clean_set(), comparison=_simple_comparison())


# ── Disclaimer checks ─────────────────────────────────────────────────────────


def test_raises_when_disclaimer_missing():
    s = _clean_set(disclaimer="")
    with pytest.raises(SafetyError) as exc_info:
        check_insight_set(s)
    assert any("disclaimer" in v for v in exc_info.value.violations)


def test_raises_when_disclaimer_whitespace_only():
    s = _clean_set(disclaimer="   ")
    with pytest.raises(SafetyError):
        check_insight_set(s)


# ── Banned diagnostic terms ───────────────────────────────────────────────────


@pytest.mark.parametrize("term, context", [
    ("diagnose", "This may diagnose a sleep disorder."),
    ("diagnosis", "A diagnosis of insomnia is possible."),
    ("disease", "This could indicate heart disease."),
    ("disorder", "A sleep disorder may be present."),
    ("pathological", "Your HRV is at a pathological level."),
    ("symptoms", "These symptoms suggest fatigue."),
    ("you have", "It appears you have a recovery deficit."),
    ("seek immediate medical", "You should seek immediate medical attention."),
])
def test_raises_on_diagnostic_term(term, context):
    s = _clean_set(insights=[_clean_insight(summary=context)])
    with pytest.raises(SafetyError) as exc_info:
        check_insight_set(s)
    assert any(term.split()[0] in v for v in exc_info.value.violations)


# ── Banned causal terms ───────────────────────────────────────────────────────


@pytest.mark.parametrize("summary", [
    "Poor sleep causes elevated stress.",
    "This was caused by your activity drop.",
    "The fatigue is due to your low HRV.",
    "Reduced sleep results in higher cortisol.",
    "This leads to recovery issues.",
    "Because of your late bedtime, your HRV dropped.",
])
def test_raises_on_causal_term(summary):
    s = _clean_set(insights=[_clean_insight(summary=summary)])
    with pytest.raises(SafetyError):
        check_insight_set(s)


def test_associative_phrasing_passes():
    good_summaries = [
        "Your HRV may be linked to recent training load.",
        "Lower sleep and higher stress appear to co-occur this week.",
        "These patterns are often associated with reduced recovery.",
        "Your body may benefit from additional rest tonight.",
    ]
    for summary in good_summaries:
        check_insight_set(_clean_set(insights=[_clean_insight(summary=summary)]))


# ── Multi-step action detection ───────────────────────────────────────────────


@pytest.mark.parametrize("action", [
    "1. Drink water. 2. Go to bed early.",
    "Step 1: Reduce screen time before bed.",
    "First, eat a light dinner, then go for a walk.",
    "2. Take a 20-minute walk.",
])
def test_raises_on_multi_step_action(action):
    s = _clean_set(insights=[_clean_insight(action=action)])
    with pytest.raises(SafetyError) as exc_info:
        check_insight_set(s)
    assert any("action" in v for v in exc_info.value.violations)


def test_single_action_passes():
    good_actions = [
        "Go to bed 30 minutes earlier tonight.",
        "Take a 20-minute walk before dinner.",
        "Limit screen time to one hour before bed.",
        "Drink an extra glass of water this afternoon.",
    ]
    for action in good_actions:
        check_insight_set(_clean_set(insights=[_clean_insight(action=action)]))


# ── Source signal provenance ──────────────────────────────────────────────────


def test_raises_when_source_signal_not_in_comparison():
    comparison = _simple_comparison()
    s = _clean_set(insights=[_clean_insight(source_signals=["nonexistent_metric"])])
    with pytest.raises(SafetyError) as exc_info:
        check_insight_set(s, comparison=comparison)
    assert any("nonexistent_metric" in v for v in exc_info.value.violations)


def test_known_metric_signal_passes():
    comparison = _simple_comparison()
    s = _clean_set(insights=[_clean_insight(source_signals=["hrv", "sleep_duration"])])
    check_insight_set(s, comparison=comparison)


def test_association_signal_counts_as_known():
    comparison = _simple_comparison()
    assoc = CandidateAssociation(
        relation="r1",
        signals=["custom_signal"],
        description="test",
        kind="association",
    )
    comparison = comparison.model_copy(update={"candidate_associations": [assoc]})
    s = _clean_set(insights=[_clean_insight(source_signals=["custom_signal"])])
    check_insight_set(s, comparison=comparison)


# ── violations() helper ───────────────────────────────────────────────────────


def test_violations_returns_empty_for_clean_insight():
    assert violations(_clean_set()) == []


def test_violations_returns_list_for_bad_insight():
    s = _clean_set(
        disclaimer="",
        insights=[_clean_insight(summary="This causes stress.")],
    )
    v = violations(s)
    assert len(v) >= 2  # disclaimer + causal term


# ── Multiple insights all checked ─────────────────────────────────────────────


def test_all_insights_are_validated():
    bad = _clean_insight(summary="This disease is causing your fatigue.")
    good = _clean_insight()
    s = _clean_set(insights=[good, bad])
    with pytest.raises(SafetyError) as exc_info:
        check_insight_set(s)
    assert any("insight[1]" in v for v in exc_info.value.violations)
