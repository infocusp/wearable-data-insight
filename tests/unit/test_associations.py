"""Unit tests for associations.py (FR-010, US3)."""

from __future__ import annotations

import pytest

from wearable_insights.associations import compute_associations
from wearable_insights.models import (
    CandidateAssociation,
    ComparisonObject,
    DataQuality,
    MetricComparison,
    WindowComparison,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mc(trend: str) -> MetricComparison:
    """Minimal MetricComparison with only the monthly trend set (used by association rules)."""
    return MetricComparison(monthly=WindowComparison(trend=trend))


def _comparison(
    *,
    sleep_duration: str = "stable",
    sleep_score: str = "stable",
    deep_sleep: str = "stable",
    rem_sleep: str = "stable",
    resting_hr: str = "stable",
    hrv: str = "stable",
    stress: str = "stable",
    steps: str = "stable",
    active_minutes: str = "stable",
) -> ComparisonObject:
    from datetime import date

    return ComparisonObject(
        user_id="u1",
        analysis_date=date(2026, 6, 17),
        sleep={
            "sleep_duration": _mc(sleep_duration),
            "sleep_score": _mc(sleep_score),
            "deep_sleep": _mc(deep_sleep),
            "rem_sleep": _mc(rem_sleep),
        },
        heart_health={
            "resting_hr": _mc(resting_hr),
            "hrv": _mc(hrv),
            "stress": _mc(stress),
        },
        activity={
            "steps": _mc(steps),
            "active_minutes": _mc(active_minutes),
        },
        candidate_associations=[],
        data_quality=DataQuality(),
    )


# ── R1: sleep ↓ & stress ↑ ───────────────────────────────────────────────────


def test_r1_fires_when_sleep_down_and_stress_up():
    co = _comparison(sleep_duration="down", stress="up")
    assocs = compute_associations(co)
    relations = [a.relation for a in assocs]
    assert "poor_sleep_and_higher_stress_co_occur" in relations


def test_r1_does_not_fire_when_only_sleep_down():
    co = _comparison(sleep_duration="down", stress="stable")
    relations = [a.relation for a in compute_associations(co)]
    assert "poor_sleep_and_higher_stress_co_occur" not in relations


def test_r1_does_not_fire_when_only_stress_up():
    co = _comparison(sleep_duration="stable", stress="up")
    relations = [a.relation for a in compute_associations(co)]
    assert "poor_sleep_and_higher_stress_co_occur" not in relations


# ── R2: steps ↓ & sleep ↓ ────────────────────────────────────────────────────


def test_r2_fires_when_steps_down_and_sleep_down():
    co = _comparison(steps="down", sleep_duration="down")
    relations = [a.relation for a in compute_associations(co)]
    assert "lower_activity_and_lower_sleep_co_occur" in relations


def test_r2_does_not_fire_when_steps_up_sleep_down():
    co = _comparison(steps="up", sleep_duration="down")
    relations = [a.relation for a in compute_associations(co)]
    assert "lower_activity_and_lower_sleep_co_occur" not in relations


# ── R3: hrv ↓ & stress ↑ ─────────────────────────────────────────────────────


def test_r3_fires_when_hrv_down_and_stress_up():
    co = _comparison(hrv="down", stress="up")
    relations = [a.relation for a in compute_associations(co)]
    assert "reduced_recovery_and_higher_stress_co_occur" in relations


def test_r3_does_not_fire_when_hrv_stable():
    co = _comparison(hrv="stable", stress="up")
    relations = [a.relation for a in compute_associations(co)]
    assert "reduced_recovery_and_higher_stress_co_occur" not in relations


# ── Multiple rules can fire simultaneously ────────────────────────────────────


def test_multiple_rules_can_fire_together():
    co = _comparison(sleep_duration="down", stress="up", hrv="down", steps="down")
    assocs = compute_associations(co)
    relations = {a.relation for a in assocs}
    assert "poor_sleep_and_higher_stress_co_occur" in relations
    assert "lower_activity_and_lower_sleep_co_occur" in relations
    assert "reduced_recovery_and_higher_stress_co_occur" in relations


# ── No rules fire ─────────────────────────────────────────────────────────────


def test_empty_result_when_no_rule_fires():
    co = _comparison()  # all stable
    assert compute_associations(co) == []


def test_empty_result_when_all_metrics_up():
    co = _comparison(
        sleep_duration="up", sleep_score="up", deep_sleep="up", rem_sleep="up",
        hrv="up", stress="up", steps="up", active_minutes="up", resting_hr="up",
    )
    # stress up but no sleep down or hrv down that pair with it → R1/R3 need sleep/hrv down
    assocs = compute_associations(co)
    # R1 needs sleep down (not up), R2 needs steps/sleep down (not up)
    relations = {a.relation for a in assocs}
    assert "lower_activity_and_lower_sleep_co_occur" not in relations
    assert "poor_sleep_and_higher_stress_co_occur" not in relations


# ── Kind is always "association" (never causation) ───────────────────────────


def test_all_associations_have_kind_association():
    co = _comparison(sleep_duration="down", stress="up", hrv="down", steps="down")
    for assoc in compute_associations(co):
        assert assoc.kind == "association", f"Expected 'association', got '{assoc.kind}'"


def test_no_causal_language_in_descriptions():
    """Guard against accidentally causal wording in the static descriptions."""
    causal_terms = ["causes", "caused by", "due to", "results in", "leads to", "because of"]
    co = _comparison(sleep_duration="down", stress="up", hrv="down", steps="down")
    for assoc in compute_associations(co):
        for term in causal_terms:
            assert term.lower() not in assoc.description.lower(), (
                f"Causal term '{term}' found in description for '{assoc.relation}'"
            )


# ── Signals list is non-empty and correct ─────────────────────────────────────


def test_r1_signals_correct():
    co = _comparison(sleep_duration="down", stress="up")
    assoc = next(a for a in compute_associations(co)
                 if a.relation == "poor_sleep_and_higher_stress_co_occur")
    assert "sleep_duration" in assoc.signals
    assert "stress" in assoc.signals


def test_r3_signals_correct():
    co = _comparison(hrv="down", stress="up")
    assoc = next(a for a in compute_associations(co)
                 if a.relation == "reduced_recovery_and_higher_stress_co_occur")
    assert "hrv" in assoc.signals
    assert "stress" in assoc.signals


# ── Determinism ───────────────────────────────────────────────────────────────


def test_compute_associations_is_deterministic():
    co = _comparison(sleep_duration="down", stress="up", hrv="down", steps="down")
    result1 = compute_associations(co)
    result2 = compute_associations(co)
    assert [a.relation for a in result1] == [a.relation for a in result2]


def test_result_order_is_rule_table_order():
    """Associations come out in R1, R2, R3 order."""
    co = _comparison(sleep_duration="down", stress="up", hrv="down", steps="down")
    relations = [a.relation for a in compute_associations(co)]
    assert relations == [
        "poor_sleep_and_higher_stress_co_occur",
        "lower_activity_and_lower_sleep_co_occur",
        "reduced_recovery_and_higher_stress_co_occur",
    ]
