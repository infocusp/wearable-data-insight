"""Unit/golden tests for deterministic live-anomaly detection (Feature 003).

No API key needed — detection is pure Python over the seeded live buffer.
"""

from __future__ import annotations

from wearable_insights.config import DEVICE_SAMPLE_MINUTES, LIVE_BUFFER_POINTS
from wearable_insights.data import live
from wearable_insights.live_anomaly import detect_live_anomalies
from wearable_insights.models import AnomalyCode, AnomalyTheme

_RECORD = {"resting_hr": 58, "hrv_rmssd_ms": 55.0}
_START = 8 * 60


def _buffer(mode: str):
    anchors = live.live_baselines(_RECORD)
    buf = live.seed_buffer(anchors, mode, _START, LIVE_BUFFER_POINTS, DEVICE_SAMPLE_MINUTES)
    return buf, anchors


def _flat_buffer(anchors: dict, **overrides):
    """A noiseless buffer pinned to the anchor values, with optional per-signal overrides."""
    base = dict(anchors)
    base.update(overrides)
    return [
        {"minute": i, "clock": "08:00", "mode": "test", **base}
        for i in range(LIVE_BUFFER_POINTS)
    ]


# ── US1: stressed context fires stress (HR) + recovery (HRV) ──────────────────


def test_stressed_buffer_fires_hr_and_hrv() -> None:
    buf, anchors = _buffer("stressed")
    anomalies = detect_live_anomalies(buf, anchors, "stressed")
    codes = {a.code for a in anomalies}
    assert AnomalyCode.hr_elevated in codes
    assert AnomalyCode.hrv_depressed in codes
    # Themes map correctly for nudge consolidation.
    by_code = {a.code: a for a in anomalies}
    assert by_code[AnomalyCode.hr_elevated].theme == AnomalyTheme.stress
    assert by_code[AnomalyCode.hrv_depressed].theme == AnomalyTheme.recovery


def test_detection_is_reproducible() -> None:
    """SC-003: same seed + context → identical anomalies in identical order."""
    buf1, anchors = _buffer("stressed")
    buf2, _ = _buffer("stressed")
    a1 = detect_live_anomalies(buf1, anchors, "stressed")
    a2 = detect_live_anomalies(buf2, anchors, "stressed")
    assert [a.model_dump() for a in a1] == [a.model_dump() for a in a2]


def test_resting_buffer_is_quiet() -> None:
    buf, anchors = _buffer("resting")
    # Resting sits at the anchor (modulo small noise) → no sustained deviation.
    assert detect_live_anomalies(buf, anchors, "resting") == []


def test_transient_spike_does_not_fire() -> None:
    """FR-005: a single out-of-band sample cannot move the windowed mean past threshold."""
    anchors = live.live_baselines(_RECORD)
    buf = _flat_buffer(anchors)  # pinned at the anchor → no sustained deviation
    spike = dict(buf[-1])
    spike["hr"] = 130  # one transient spike (>> anchor) at the tail
    buf.append(spike)
    anomalies = detect_live_anomalies(buf, anchors, "resting")
    assert all(a.code != AnomalyCode.hr_elevated for a in anomalies)


# ── US2: SpO₂ / skin-temp / respiration each fire independently ───────────────


def test_spo2_low_fires_vitals() -> None:
    anchors = live.live_baselines(_RECORD)
    buf = _flat_buffer(anchors, spo2=94.0)  # ~3.7% below → significant
    anomalies = detect_live_anomalies(buf, anchors)
    hit = [a for a in anomalies if a.code == AnomalyCode.spo2_low]
    assert hit and hit[0].theme == AnomalyTheme.vitals


def test_skin_temp_elevated_fires_vitals() -> None:
    anchors = live.live_baselines(_RECORD)
    buf = _flat_buffer(anchors, skin_temp=37.7)  # ~2.7% above → significant
    anomalies = detect_live_anomalies(buf, anchors)
    assert any(a.code == AnomalyCode.skin_temp_elevated for a in anomalies)


def test_resp_rate_elevated_fires_vitals() -> None:
    anchors = live.live_baselines(_RECORD)
    buf = _flat_buffer(anchors, resp_rate=18.0)  # ~28% above → significant/critical
    anomalies = detect_live_anomalies(buf, anchors)
    assert any(a.code == AnomalyCode.resp_rate_elevated for a in anomalies)


def test_benign_direction_does_not_fire() -> None:
    """High SpO₂ / low skin-temp / low respiration are not 'concerning' directions."""
    anchors = live.live_baselines(_RECORD)
    buf = _flat_buffer(anchors, spo2=100.0, skin_temp=35.0, resp_rate=10.0)
    codes = {a.code for a in detect_live_anomalies(buf, anchors)}
    assert AnomalyCode.spo2_low not in codes
    assert AnomalyCode.skin_temp_elevated not in codes
    assert AnomalyCode.resp_rate_elevated not in codes


def test_insufficient_samples_yields_nothing() -> None:
    anchors = live.live_baselines(_RECORD)
    buf = _flat_buffer(anchors, spo2=90.0)[:2]  # below LIVE_ANOMALY_MIN_SAMPLES
    assert detect_live_anomalies(buf, anchors) == []
