"""Unit tests for live-anomaly detection using slotted baselines (Feature 004).

These complement test_live_anomaly.py (which tests the legacy flat-dict path) by
exercising the SlottedBaselineSet path: time-of-day sensitivity, multi-horizon
ComparisonObject shape, and reproducibility under slotted lookup.

No API key needed.
"""

from __future__ import annotations

from datetime import date

import pytest

from wearable_insights.config import DEVICE_SAMPLE_MINUTES, LIVE_BUFFER_POINTS
from wearable_insights.data import live
from wearable_insights.data.slotted_baselines import (
    SlottedBaselineSet,
    build_slotted_baselines,
    lookup_anchor,
    slot_index,
)
from wearable_insights.live_anomaly import detect_live_anomalies, synthesize_comparison
from wearable_insights.models import AnomalyCode, WindowComparison

_RECORD = {"resting_hr": 58, "hrv_rmssd_ms": 55.0}
_REF_DATE = date(2026, 6, 24)  # Tuesday


@pytest.fixture(scope="module")
def slotted() -> SlottedBaselineSet:
    return build_slotted_baselines(
        _RECORD,
        seed=42,
        history_days=30,
        horizons=(7, 30),
        min_samples=3,
        sample_step_minutes=5,
        ref_date=_REF_DATE,
    )


def _flat_buffer_at_anchor(slotted: SlottedBaselineSet, signal: str, slot: int, dt: str) -> list[dict]:
    """Return a noiseless buffer where signal values equal the slot's 30d bucket average."""
    anchor = lookup_anchor(slotted, signal, slot, dt, 30) or slotted.flat_anchors[signal]
    flat = dict(slotted.flat_anchors)
    flat[signal] = anchor
    return [
        {"minute": slot * 180 + i * DEVICE_SAMPLE_MINUTES, "clock": "10:00", "mode": "resting", **flat}
        for i in range(LIVE_BUFFER_POINTS)
    ]


def _flat_buffer_elevated(
    slotted: SlottedBaselineSet,
    signal: str,
    slot: int,
    dt: str,
    factor: float,
) -> list[dict]:
    """Buffer with *signal* elevated to ``anchor * factor`` for the given slot."""
    anchor = lookup_anchor(slotted, signal, slot, dt, 30) or slotted.flat_anchors[signal]
    flat = dict(slotted.flat_anchors)
    flat[signal] = anchor * factor
    return [
        {"minute": slot * 180 + i * DEVICE_SAMPLE_MINUTES, "clock": "10:00", "mode": "resting", **flat}
        for i in range(LIVE_BUFFER_POINTS)
    ]


# ── SC-001: no false positive when values track the slot average ───────────────


def test_no_anomaly_when_values_match_slot_average(slotted: SlottedBaselineSet) -> None:
    """SC-001: a buffer sitting at its slot's bucket average must not raise an anomaly."""
    slot = 3  # 09:00–12:00
    buf = _flat_buffer_at_anchor(slotted, "hr", slot, "weekday")
    anomalies = detect_live_anomalies(
        buf,
        slotted,
        current_minute=slot * 180 + 90,
        current_day_type="weekday",
    )
    hr_anomalies = [a for a in anomalies if a.code == AnomalyCode.hr_elevated]
    assert hr_anomalies == [], "HR at its slot average should not fire"


# ── SC-002: anomaly fires when sustained above dead-band ─────────────────────


def test_anomaly_fires_when_sustained_above_dead_band(slotted: SlottedBaselineSet) -> None:
    """SC-002: HR elevated 40% above slot average fires hr_elevated."""
    slot = 3
    buf = _flat_buffer_elevated(slotted, "hr", slot, "weekday", factor=1.40)
    anomalies = detect_live_anomalies(
        buf,
        slotted,
        current_minute=slot * 180 + 90,
        current_day_type="weekday",
    )
    codes = {a.code for a in anomalies}
    assert AnomalyCode.hr_elevated in codes


# ── SC-003: same raw value → different outcome in different slots ─────────────


def test_time_of_day_sensitivity(slotted: SlottedBaselineSet) -> None:
    """SC-003: identical raw HR value evaluated in two slots with different averages
    should produce different deviation outcomes."""
    # Pick a raw HR that is high for early morning (slot 0) but moderate for midday (slot 4).
    midday_anchor = lookup_anchor(slotted, "hr", 4, "weekday", 30) or 80.0
    # Set HR to 1.35× the midday anchor.  For midday it's 35% elevated (significant).
    # For overnight (slot 0) the anchor is lower, so the deviation may be even larger.
    raw_hr = midday_anchor * 1.35

    def _buf(slot: int) -> list[dict]:
        flat = dict(slotted.flat_anchors)
        flat["hr"] = raw_hr
        return [
            {"minute": slot * 180 + i * DEVICE_SAMPLE_MINUTES, "clock": "10:00", "mode": "resting", **flat}
            for i in range(LIVE_BUFFER_POINTS)
        ]

    anomalies_midday = detect_live_anomalies(
        _buf(4), slotted, current_minute=4 * 180 + 90, current_day_type="weekday"
    )
    midday_hr = [a for a in anomalies_midday if a.code == AnomalyCode.hr_elevated]

    anomalies_overnight = detect_live_anomalies(
        _buf(0), slotted, current_minute=0 * 180 + 90, current_day_type="weekday"
    )
    overnight_hr = [a for a in anomalies_overnight if a.code == AnomalyCode.hr_elevated]

    # At least one slot must fire (the raw value is genuinely elevated vs its slot anchor).
    assert midday_hr or overnight_hr, "Raw elevated HR should fire in at least one slot"

    # If both fire, the detail text must reference different slot labels.
    if midday_hr and overnight_hr:
        assert midday_hr[0].detail != overnight_hr[0].detail


# ── SC-004: reproducibility under slotted path ───────────────────────────────


def test_detection_reproducible_with_slotted_baselines(slotted: SlottedBaselineSet) -> None:
    """SC-004: same buffer + baselines → identical anomalies both runs."""
    slot = 3
    buf = _flat_buffer_elevated(slotted, "hr", slot, "weekday", factor=1.40)
    a1 = detect_live_anomalies(buf, slotted, current_minute=slot * 180 + 90, current_day_type="weekday")
    a2 = detect_live_anomalies(buf, slotted, current_minute=slot * 180 + 90, current_day_type="weekday")
    assert [a.model_dump() for a in a1] == [a.model_dump() for a in a2]


# ── US2: multi-horizon ComparisonObject ──────────────────────────────────────


def test_synthesize_comparison_has_weekly_and_monthly(slotted: SlottedBaselineSet) -> None:
    """US2: synthesized comparison carries both weekly (7d) and monthly (30d) windows."""
    slot = 3
    buf = _flat_buffer_elevated(slotted, "hr", slot, "weekday", factor=1.40)
    anomalies = detect_live_anomalies(
        buf, slotted, current_minute=slot * 180 + 90, current_day_type="weekday"
    )
    hr_anomalies = [a for a in anomalies if a.code == AnomalyCode.hr_elevated]
    assert hr_anomalies, "Need an HR anomaly to check comparison shape"

    comparison = synthesize_comparison(
        anomalies,
        buf,
        slotted,
        user_id="test",
        analysis_date=_REF_DATE,
        current_minute=slot * 180 + 90,
        current_day_type="weekday",
    )
    assert "hr" in comparison.heart_health
    mc = comparison.heart_health["hr"]

    assert mc.monthly.baseline_value is not None, "monthly window baseline must be populated"
    assert mc.monthly.percentage_change is not None
    assert mc.weekly.baseline_value is not None, "weekly window baseline must be populated"
    assert mc.weekly.percentage_change is not None


def test_synthesize_comparison_evaluation_tags_set(slotted: SlottedBaselineSet) -> None:
    """Evaluation tags in the comparison must match anomaly direction."""
    slot = 3
    buf = _flat_buffer_elevated(slotted, "hr", slot, "weekday", factor=1.40)
    anomalies = detect_live_anomalies(
        buf, slotted, current_minute=slot * 180 + 90, current_day_type="weekday"
    )
    comparison = synthesize_comparison(
        anomalies, buf, slotted, "test", _REF_DATE,
        current_minute=slot * 180 + 90, current_day_type="weekday",
    )
    if "hr" in comparison.heart_health:
        tag = comparison.heart_health["hr"].monthly.evaluation_tag
        assert "Elevated" in tag or "Stable" in tag, f"Unexpected tag: {tag}"


# ── Anomaly detail text includes time-of-day context ─────────────────────────


def test_anomaly_detail_includes_time_context(slotted: SlottedBaselineSet) -> None:
    """Anomaly detail should mention 'time of day' for explainability (FR-012)."""
    slot = 3
    buf = _flat_buffer_elevated(slotted, "hr", slot, "weekday", factor=1.40)
    anomalies = detect_live_anomalies(
        buf, slotted, current_minute=slot * 180 + 90, current_day_type="weekday"
    )
    hr_anomalies = [a for a in anomalies if a.code == AnomalyCode.hr_elevated]
    assert hr_anomalies
    detail = hr_anomalies[0].detail
    assert "time of day" in detail.lower(), f"Detail missing time-of-day context: {detail!r}"
    assert "weekday" in detail.lower(), f"Detail missing day-type: {detail!r}"


# ── Backward compat: flat dict still accepted ─────────────────────────────────


def test_flat_dict_still_accepted() -> None:
    """Legacy flat-dict path must still work unchanged (no regression)."""
    flat = live.live_baselines(_RECORD)
    buf = live.seed_buffer(flat, "stressed", 8 * 60, LIVE_BUFFER_POINTS, DEVICE_SAMPLE_MINUTES)
    # No current_minute / current_day_type needed for flat dict.
    anomalies = detect_live_anomalies(buf, flat, "stressed")
    assert any(a.code == AnomalyCode.hr_elevated for a in anomalies)
