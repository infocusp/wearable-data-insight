"""Unit tests for the synthesized ComparisonObject built from live anomalies (Feature 003)."""

from __future__ import annotations

from datetime import date

import pytest

from wearable_insights.config import LIVE_BUFFER_POINTS
from wearable_insights.live_anomaly import detect_live_anomalies, synthesize_comparison
from wearable_insights.models import ComparisonObject

_ANCHORS = {"hr": 70.0, "hrv": 55.0, "spo2": 97.6, "skin_temp": 36.7, "resp_rate": 14.0}


def _flat_buffer(**overrides):
    base = dict(_ANCHORS)
    base.update(overrides)
    return [{"minute": i, "clock": "08:00", "mode": "test", **base} for i in range(LIVE_BUFFER_POINTS)]


def test_synthesize_places_signal_under_heart_health() -> None:
    buf = _flat_buffer(spo2=94.0)
    anomalies = detect_live_anomalies(buf, _ANCHORS)
    comp = synthesize_comparison(anomalies, buf, _ANCHORS, "u1", date(2026, 6, 24))

    assert isinstance(comp, ComparisonObject)
    assert comp.user_id == "u1"
    assert "spo2" in comp.heart_health
    assert comp.sleep == {} and comp.activity == {}

    mc = comp.heart_health["spo2"]
    assert mc.current_value == pytest.approx(94.0)
    assert mc.monthly.baseline_value == pytest.approx(97.6)
    assert mc.monthly.percentage_change < 0
    assert mc.monthly.trend == "down"
    assert mc.monthly.evaluation_tag == "Significantly Depressed"


def test_synthesize_elevated_signal_tag() -> None:
    buf = _flat_buffer(hr=92.0)  # ~31% above → significant elevated
    anomalies = detect_live_anomalies(buf, _ANCHORS)
    comp = synthesize_comparison(anomalies, buf, _ANCHORS, "u1", date(2026, 6, 24))
    mc = comp.heart_health["hr"]
    assert mc.monthly.percentage_change > 0
    assert mc.monthly.trend == "up"
    assert mc.monthly.evaluation_tag in ("Significantly Elevated", "Critically Elevated")


def test_synthesize_empty_when_no_anomalies() -> None:
    comp = synthesize_comparison([], _flat_buffer(), _ANCHORS, "u1", date(2026, 6, 24))
    assert comp.heart_health == {}
