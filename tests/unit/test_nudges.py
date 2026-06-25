"""Unit tests for nudge consolidation (T011, FR-005, FR-006, SC-008)."""

from __future__ import annotations

from datetime import date

import pytest

from wearable_insights.config import DISCLAIMER, MAX_NUDGES_PER_DAY
from wearable_insights.models import (
    Anomaly,
    AnomalyCode,
    AnomalySeverity,
    AnomalyTheme,
    ComparisonObject,
    DataQuality,
    Insight,
    InsightSet,
    MetricComparison,
    NudgeSet,
    WindowComparison,
)
from wearable_insights.nudges import consolidate_nudge_groups, generate_nudge_set


# ── Helpers ───────────────────────────────────────────────────────────────────

def _anomaly(code: str, theme: str, severity: str = "critical", signals: list[str] | None = None) -> Anomaly:
    return Anomaly(
        code=AnomalyCode(code),
        theme=AnomalyTheme(theme),
        severity=AnomalySeverity(severity),
        signals=signals or [code.split("_")[0]],
        evaluation_tag="Critically Elevated" if severity == "critical" else "Significantly Depressed",
        detail=f"{code} detected",
    )


def _stub_insight_set(signal: str = "stress") -> InsightSet:
    return InsightSet(
        insights=[
            Insight(
                title="Stub nudge",
                summary="Your metrics may be linked to recovery patterns.",
                action="Take a short walk this evening.",
                confidence="high",
                source_signals=[signal],
            )
        ],
        disclaimer=DISCLAIMER,
        generated_from=[signal],
    )


def _stable_comparison() -> ComparisonObject:
    stable_win = WindowComparison(
        baseline_value=100.0,
        percentage_change=2.0,
        trend="stable",
        evaluation_tag="Stable / Within Normal Baseline",
    )
    mc = MetricComparison(current_value=102.0, monthly=stable_win)
    return ComparisonObject(
        user_id="u1",
        analysis_date=date(2026, 6, 17),
        heart_health={"stress": mc, "hrv": mc},
        activity={"steps": mc, "active_minutes": mc},
        sleep={"sleep_duration": mc, "sleep_score": mc},
        data_quality=DataQuality(),
    )


def _multi_anomalies() -> list[Anomaly]:
    return [
        _anomaly("stress_elevated", "stress", "critical", ["stress"]),
        _anomaly("hrv_depressed", "recovery", "significant", ["hrv"]),
        _anomaly("steps_low", "activity", "critical", ["steps"]),
        _anomaly("active_minutes_low", "activity", "critical", ["active_minutes"]),
        _anomaly("sleep_insufficient", "sleep", "significant", ["sleep_duration"]),
        _anomaly("sleep_quality_low", "sleep", "critical", ["sleep_score"]),
    ]


# ── FR-005: zero nudges on clean day ─────────────────────────────────────────

def test_no_anomalies_yields_empty_nudge_set():
    """FR-005: a day with no anomalies must produce no nudges."""
    ns = generate_nudge_set(
        anomalies=[],
        comparison=_stable_comparison(),
        generate_fn=lambda c: _stub_insight_set(),
    )
    assert isinstance(ns, NudgeSet)
    assert ns.nudges == []


# ── FR-006 / SC-008: cap at MAX_NUDGES_PER_DAY ───────────────────────────────

def test_nudge_count_is_capped(monkeypatch):
    """SC-008: multiple anomalies produce at most MAX_NUDGES_PER_DAY nudges."""
    call_count = 0

    def _counting_generate(c):
        nonlocal call_count
        call_count += 1
        theme_signals = list(c.sleep.keys() or c.heart_health.keys() or c.activity.keys() or ["stress"])
        sig = theme_signals[0] if theme_signals else "stress"
        return _stub_insight_set(sig)

    ns = generate_nudge_set(
        anomalies=_multi_anomalies(),
        comparison=_stable_comparison(),
        generate_fn=_counting_generate,
    )
    assert len(ns.nudges) <= MAX_NUDGES_PER_DAY
    assert call_count <= MAX_NUDGES_PER_DAY


def test_nudge_count_does_not_exceed_3_with_6_anomalies():
    ns = generate_nudge_set(
        anomalies=_multi_anomalies(),
        comparison=_stable_comparison(),
        generate_fn=lambda c: _stub_insight_set("stress"),
    )
    assert len(ns.nudges) <= 3


# ── Grouping by theme ─────────────────────────────────────────────────────────

def test_same_theme_anomalies_grouped_into_one_nudge():
    """Two activity anomalies (steps_low, active_minutes_low) → one nudge."""
    anomalies = [
        _anomaly("steps_low", "activity", "critical", ["steps"]),
        _anomaly("active_minutes_low", "activity", "critical", ["active_minutes"]),
    ]
    ns = generate_nudge_set(
        anomalies=anomalies,
        comparison=_stable_comparison(),
        generate_fn=lambda c: _stub_insight_set("steps"),
    )
    activity_nudges = [n for n in ns.nudges if n.theme.value == "activity"]
    assert len(activity_nudges) == 1
    assert len(activity_nudges[0].anomalies) == 2


def test_triggered_by_contains_all_anomaly_signals():
    """Nudge.triggered_by is the union of all anomaly signals for that theme."""
    anomalies = [
        _anomaly("steps_low", "activity", "critical", ["steps"]),
        _anomaly("active_minutes_low", "activity", "critical", ["active_minutes"]),
    ]
    ns = generate_nudge_set(
        anomalies=anomalies,
        comparison=_stable_comparison(),
        generate_fn=lambda c: _stub_insight_set("steps"),
    )
    activity_nudge = next(n for n in ns.nudges if n.theme.value == "activity")
    assert "steps" in activity_nudge.triggered_by
    assert "active_minutes" in activity_nudge.triggered_by


# ── Severity priority: most severe theme first ────────────────────────────────

def test_highest_severity_theme_comes_first():
    """Groups are ordered by max severity so the most urgent nudge is first."""
    anomalies = [
        _anomaly("sleep_insufficient", "sleep", "moderate", ["sleep_duration"]),
        _anomaly("stress_elevated", "stress", "critical", ["stress"]),
    ]
    ns = generate_nudge_set(
        anomalies=anomalies,
        comparison=_stable_comparison(),
        generate_fn=lambda c: _stub_insight_set("stress"),
    )
    if len(ns.nudges) >= 2:
        assert ns.nudges[0].severity.value in ("critical", "significant")


# ── NudgeSet structure ────────────────────────────────────────────────────────

def test_nudge_has_disclaimer():
    anomalies = [_anomaly("stress_elevated", "stress", "critical", ["stress"])]
    ns = generate_nudge_set(
        anomalies=anomalies,
        comparison=_stable_comparison(),
        generate_fn=lambda c: _stub_insight_set("stress"),
    )
    assert ns.nudges[0].disclaimer


def test_nudge_has_nudge_id():
    anomalies = [_anomaly("stress_elevated", "stress", "critical", ["stress"])]
    ns = generate_nudge_set(
        anomalies=anomalies,
        comparison=_stable_comparison(),
        generate_fn=lambda c: _stub_insight_set("stress"),
    )
    assert ns.nudges[0].nudge_id


def test_nudge_id_is_stable():
    """Same user/date/theme always produces the same nudge_id."""
    anomalies = [_anomaly("stress_elevated", "stress", "critical", ["stress"])]
    comparison = _stable_comparison()
    ns1 = generate_nudge_set(anomalies=anomalies, comparison=comparison, generate_fn=lambda c: _stub_insight_set())
    ns2 = generate_nudge_set(anomalies=anomalies, comparison=comparison, generate_fn=lambda c: _stub_insight_set())
    assert ns1.nudges[0].nudge_id == ns2.nudges[0].nudge_id
