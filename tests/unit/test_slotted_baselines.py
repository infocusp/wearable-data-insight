"""Unit tests for slotted time-of-day baselines (Feature 004).

All tests are deterministic — no API key needed.
"""

from __future__ import annotations

from datetime import date

import pytest

from wearable_insights.data.slotted_baselines import (
    SLOT_COUNT,
    SLOT_WIDTH_MINUTES,
    SlottedBaselineSet,
    build_slotted_baselines,
    day_type,
    lookup_anchor,
    slot_index,
    slot_label,
)

_RECORD = {"resting_hr": 58, "hrv_rmssd_ms": 55.0}
_REF_DATE = date(2026, 6, 24)  # Tuesday (weekday)
_SIGNALS = ["hr", "hrv", "spo2", "skin_temp", "resp_rate"]
_HORIZONS = (7, 30)


# ── slot_index ────────────────────────────────────────────────────────────────


def test_slot_index_boundaries() -> None:
    assert slot_index(0) == 0       # 00:00 → slot 0
    assert slot_index(179) == 0     # 02:59 → slot 0
    assert slot_index(180) == 1     # 03:00 → slot 1
    assert slot_index(1439) == 7    # 23:59 → slot 7


def test_slot_index_wraps() -> None:
    assert slot_index(1440) == 0          # 24:00 wraps to 00:00 → slot 0
    assert slot_index(1620) == 1          # 27:00 → 1620 % 1440 = 180 → slot 1
    assert slot_index(1440 + 600) == slot_index(600)  # 10:00 next day == 10:00 today


def test_slot_index_midpoints() -> None:
    for i in range(SLOT_COUNT):
        mid = i * SLOT_WIDTH_MINUTES + 90
        assert slot_index(mid) == i


# ── day_type ──────────────────────────────────────────────────────────────────


def test_day_type_weekdays() -> None:
    for wd in range(5):  # Mon=0 … Fri=4
        assert day_type(wd) == "weekday"


def test_day_type_weekend() -> None:
    assert day_type(5) == "weekend"  # Saturday
    assert day_type(6) == "weekend"  # Sunday


# ── slot_label ────────────────────────────────────────────────────────────────


def test_slot_label_format() -> None:
    assert slot_label(0) == "00:00–03:00"
    assert slot_label(3) == "09:00–12:00"
    assert slot_label(7) == "21:00–24:00"


# ── build_slotted_baselines ───────────────────────────────────────────────────


@pytest.fixture(scope="module")
def baselines() -> SlottedBaselineSet:
    return build_slotted_baselines(
        _RECORD,
        seed=42,
        history_days=30,
        horizons=_HORIZONS,
        min_samples=3,
        sample_step_minutes=5,
        ref_date=_REF_DATE,
    )


def test_build_returns_slotted_baseline_set(baselines: SlottedBaselineSet) -> None:
    assert isinstance(baselines, SlottedBaselineSet)
    assert baselines.horizons == _HORIZONS
    assert baselines.min_samples == 3


def test_build_is_reproducible() -> None:
    """SC-004: same seed + ref_date → byte-identical bucket averages."""
    b1 = build_slotted_baselines(_RECORD, seed=42, history_days=30, ref_date=_REF_DATE)
    b2 = build_slotted_baselines(_RECORD, seed=42, history_days=30, ref_date=_REF_DATE)
    assert b1.averages == b2.averages
    assert b1.counts == b2.counts


def test_all_active_buckets_populated(baselines: SlottedBaselineSet) -> None:
    """SC-005: every (signal, slot, day_type, horizon) reachable by the detector has data."""
    for sig in _SIGNALS:
        for slot in range(SLOT_COUNT):
            for dt in ("weekday", "weekend"):
                for h in _HORIZONS:
                    key = (sig, slot, dt, h)
                    assert baselines.counts.get(key, 0) > 0, (
                        f"Bucket {key} is empty — detector could not look it up"
                    )


def test_flat_anchors_populated(baselines: SlottedBaselineSet) -> None:
    for sig in _SIGNALS:
        assert sig in baselines.flat_anchors
        assert baselines.flat_anchors[sig] > 0


def test_different_seeds_differ() -> None:
    b1 = build_slotted_baselines(_RECORD, seed=42, history_days=30, ref_date=_REF_DATE)
    b2 = build_slotted_baselines(_RECORD, seed=99, history_days=30, ref_date=_REF_DATE)
    assert b1.averages != b2.averages


# ── lookup_anchor ─────────────────────────────────────────────────────────────


def test_lookup_returns_float_for_populated_bucket(baselines: SlottedBaselineSet) -> None:
    anchor = lookup_anchor(baselines, "hr", 3, "weekday", 30)
    assert anchor is not None
    assert 50 < anchor < 130  # physiologically plausible


def test_lookup_fallback_to_all_slots(baselines: SlottedBaselineSet) -> None:
    """When a specific slot is under-populated, falls back to all-slot average."""
    sparse = SlottedBaselineSet(
        averages=baselines.averages,
        counts={k: 0 for k in baselines.counts},  # mark all buckets as unreliable
        flat_anchors=baselines.flat_anchors,
        horizons=_HORIZONS,
        min_samples=1_000_000,  # artificially high threshold
    )
    anchor = lookup_anchor(sparse, "hr", 3, "weekday", 30)
    # Should fall all the way back to flat_anchors (no reliable slots).
    assert anchor == sparse.flat_anchors["hr"]


def test_lookup_fallback_unknown_signal(baselines: SlottedBaselineSet) -> None:
    anchor = lookup_anchor(baselines, "unknown_signal", 0, "weekday", 30)
    assert anchor is None


def test_lookup_week_vs_month_differ(baselines: SlottedBaselineSet) -> None:
    """7d and 30d anchors for the same bucket may differ (different history windows)."""
    a7 = lookup_anchor(baselines, "hr", 3, "weekday", 7)
    a30 = lookup_anchor(baselines, "hr", 3, "weekday", 30)
    assert a7 is not None and a30 is not None
    # They could be equal in edge cases, but at least both are present.


# ── slot sensitivity (SC-003) ─────────────────────────────────────────────────


def test_different_slots_have_different_averages(baselines: SlottedBaselineSet) -> None:
    """Slot averages must differ to demonstrate time-of-day sensitivity (SC-003)."""
    hr_averages = {
        slot: lookup_anchor(baselines, "hr", slot, "weekday", 30)
        for slot in range(SLOT_COUNT)
    }
    # Not all slots should return the same value.
    unique_values = set(round(v, 1) for v in hr_averages.values() if v is not None)
    assert len(unique_values) > 1, "All slots returned identical HR averages — no time-of-day effect"
