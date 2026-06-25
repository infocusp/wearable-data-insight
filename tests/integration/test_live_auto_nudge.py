"""Integration: live buffer → synthesized comparison → reused nudge path (Feature 003).

Uses a stubbed generate-fn so no API key is needed (SC-001, SC-002).
"""

from __future__ import annotations

from datetime import date

from wearable_insights.config import DEVICE_SAMPLE_MINUTES, DISCLAIMER, LIVE_BUFFER_POINTS, MAX_NUDGES_PER_DAY
from wearable_insights.data import live
from wearable_insights.live_anomaly import detect_live_anomalies, synthesize_comparison
from wearable_insights.models import ComparisonObject, Insight, InsightSet, NudgeSet
from wearable_insights.nudges import generate_nudge_set

_RECORD = {"resting_hr": 58, "hrv_rmssd_ms": 55.0}
_ANCHORS = {"hr": 70.0, "hrv": 55.0, "spo2": 97.6, "skin_temp": 36.7, "resp_rate": 14.0}


def _stub_generate(comparison: ComparisonObject) -> InsightSet:
    sig = next(iter(comparison.heart_health or comparison.sleep or comparison.activity), "hr")
    return InsightSet(
        insights=[
            Insight(
                title="Live signal nudge",
                summary="Your recent readings may be associated with a higher-effort state.",
                action="Take five slow breaths and a short walk.",
                confidence="medium",
                source_signals=[sig],
            )
        ],
        disclaimer=DISCLAIMER,
        generated_from=[sig],
    )


def _flat_buffer(**overrides):
    base = dict(_ANCHORS)
    base.update(overrides)
    return [{"minute": i, "clock": "08:00", **base} for i in range(LIVE_BUFFER_POINTS)]


def _run(buffer, anchors):
    anomalies = detect_live_anomalies(buffer, anchors)
    comparison = synthesize_comparison(anomalies, buffer, anchors, "usr_live", date(2026, 6, 24))
    return generate_nudge_set(anomalies, comparison, generate_fn=_stub_generate)


# ── US1: stressed context auto-raises a nudge ─────────────────────────────────


def test_stressed_buffer_auto_raises_nudge() -> None:
    anchors = live.live_baselines(_RECORD)
    buf = live.seed_buffer(anchors, "stressed", 8 * 60, LIVE_BUFFER_POINTS, DEVICE_SAMPLE_MINUTES)
    ns = _run(buf, anchors)

    assert isinstance(ns, NudgeSet)
    assert ns.nudges, "stressed context should raise at least one nudge"
    assert len(ns.nudges) <= MAX_NUDGES_PER_DAY  # SC-004
    for nudge in ns.nudges:
        assert nudge.insight.title and nudge.insight.action  # exactly one action enforced by safety
        assert nudge.disclaimer == DISCLAIMER  # SC-002
        assert nudge.triggered_by  # provenance (Principle V)


# ── US2: low SpO₂ trend raises a vitals nudge ─────────────────────────────────


def test_low_spo2_raises_vitals_nudge() -> None:
    buf = _flat_buffer(spo2=93.5)
    ns = _run(buf, _ANCHORS)
    themes = {n.theme.value for n in ns.nudges}
    assert "vitals" in themes
