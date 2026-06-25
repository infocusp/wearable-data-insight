"""Unit tests for normalize.py (FR-003, FR-004)."""

from __future__ import annotations

from datetime import date

import pytest

from wearable_insights.normalize import normalize_record, normalize_records, normalize_profile


# ── Helpers ───────────────────────────────────────────────────────────────────

def _base_raw(**overrides) -> dict:
    row = {
        "user_id": "u1",
        "date": "2026-06-01",
        "sleep_duration_minutes": 420,
        "sleep_score": 74,
        "deep_sleep_minutes": 80,
        "rem_sleep_minutes": 90,
        "bedtime": "22:30",
        "resting_hr": 58,
        "hrv_rmssd_ms": 62.5,
        "stress_score": 28,
        "steps": 8500,
        "active_minutes": 45,
    }
    row.update(overrides)
    return row


# ── Happy path ────────────────────────────────────────────────────────────────


def test_happy_path_all_fields_present():
    rec = normalize_record(_base_raw())
    assert rec.user_id == "u1"
    assert rec.date == date(2026, 6, 1)
    assert rec.sleep_duration_minutes == 420
    assert rec.sleep_score == 74
    assert rec.deep_sleep_minutes == 80
    assert rec.rem_sleep_minutes == 90
    assert rec.bedtime == "22:30"
    assert rec.resting_hr == 58
    assert rec.hrv_rmssd_ms == 62.5
    assert rec.stress_score == 28
    assert rec.steps == 8500
    assert rec.active_minutes == 45
    assert rec.missing_fields == []
    assert rec.invalid_fields == []


# ── Missing fields ────────────────────────────────────────────────────────────


def test_missing_single_field():
    rec = normalize_record(_base_raw(steps=None))
    assert rec.steps is None
    assert "steps" in rec.missing_fields
    assert "steps" not in rec.invalid_fields


def test_missing_entire_sleep_group():
    raw = _base_raw(
        sleep_duration_minutes=None,
        sleep_score=None,
        deep_sleep_minutes=None,
        rem_sleep_minutes=None,
        bedtime=None,
    )
    rec = normalize_record(raw)
    for f in ("sleep_duration_minutes", "sleep_score", "deep_sleep_minutes", "rem_sleep_minutes", "bedtime"):
        assert getattr(rec, f) is None, f"{f} should be None"
        assert f in rec.missing_fields, f"{f} should be in missing_fields"


def test_absent_field_treated_as_missing():
    raw = {k: v for k, v in _base_raw().items() if k != "hrv_rmssd_ms"}
    rec = normalize_record(raw)
    assert rec.hrv_rmssd_ms is None
    assert "hrv_rmssd_ms" in rec.missing_fields


# ── Out-of-range / invalid fields ────────────────────────────────────────────


def test_out_of_range_sleep_score():
    rec = normalize_record(_base_raw(sleep_score=150))  # max is 100
    assert rec.sleep_score is None
    assert "sleep_score" in rec.invalid_fields
    assert "sleep_score" not in rec.missing_fields


def test_out_of_range_hrv_too_low():
    rec = normalize_record(_base_raw(hrv_rmssd_ms=0.5))  # min is 1.0
    assert rec.hrv_rmssd_ms is None
    assert "hrv_rmssd_ms" in rec.invalid_fields


def test_out_of_range_resting_hr_too_low():
    rec = normalize_record(_base_raw(resting_hr=20))  # min is 25
    assert rec.resting_hr is None
    assert "resting_hr" in rec.invalid_fields


def test_boundary_values_are_valid():
    rec = normalize_record(_base_raw(sleep_score=0, stress_score=100, hrv_rmssd_ms=1.0))
    assert rec.sleep_score == 0
    assert rec.stress_score == 100
    assert rec.hrv_rmssd_ms == 1.0
    assert "sleep_score" not in rec.invalid_fields
    assert "stress_score" not in rec.invalid_fields


def test_non_numeric_value_quarantined():
    rec = normalize_record(_base_raw(steps="many"))
    assert rec.steps is None
    assert "steps" in rec.invalid_fields


# ── Sleep stage sum constraint ────────────────────────────────────────────────


def test_sleep_stages_sum_exceeds_total_quarantined():
    # deep=200, rem=300, total=420 → 200+300 > 420 → both quarantined
    rec = normalize_record(_base_raw(deep_sleep_minutes=200, rem_sleep_minutes=300, sleep_duration_minutes=420))
    assert rec.deep_sleep_minutes is None
    assert rec.rem_sleep_minutes is None
    assert "deep_sleep_minutes" in rec.invalid_fields
    assert "rem_sleep_minutes" in rec.invalid_fields


def test_sleep_stages_exactly_equal_total_are_valid():
    # deep=210, rem=210, total=420 → exactly equal, valid
    rec = normalize_record(_base_raw(deep_sleep_minutes=210, rem_sleep_minutes=210, sleep_duration_minutes=420))
    assert rec.deep_sleep_minutes == 210
    assert rec.rem_sleep_minutes == 210
    assert "deep_sleep_minutes" not in rec.invalid_fields


def test_sleep_stage_check_skipped_when_duration_missing():
    rec = normalize_record(_base_raw(sleep_duration_minutes=None, deep_sleep_minutes=200, rem_sleep_minutes=300))
    # No stage constraint check when duration is null
    assert rec.deep_sleep_minutes == 200
    assert rec.rem_sleep_minutes == 300


# ── Bedtime validation ────────────────────────────────────────────────────────


def test_invalid_bedtime_quarantined():
    rec = normalize_record(_base_raw(bedtime="25:00"))
    assert rec.bedtime is None
    assert "bedtime" in rec.invalid_fields


def test_valid_bedtime_midnight():
    rec = normalize_record(_base_raw(bedtime="00:00"))
    assert rec.bedtime == "00:00"


def test_bedtime_not_a_string():
    rec = normalize_record(_base_raw(bedtime=2230))
    assert rec.bedtime is None
    assert "bedtime" in rec.invalid_fields


# ── Coercion ──────────────────────────────────────────────────────────────────


def test_float_coerced_to_int_for_integer_fields():
    rec = normalize_record(_base_raw(sleep_duration_minutes=419.7))
    assert rec.sleep_duration_minutes == 420
    assert isinstance(rec.sleep_duration_minutes, int)


def test_string_numeric_coerced():
    rec = normalize_record(_base_raw(steps="9000"))
    assert rec.steps == 9000


# ── Never raises ─────────────────────────────────────────────────────────────


def test_completely_empty_raw_does_not_raise():
    rec = normalize_record({})
    assert rec.user_id == ""
    assert all(getattr(rec, f) is None for f in (
        "sleep_duration_minutes", "sleep_score", "deep_sleep_minutes",
        "rem_sleep_minutes", "bedtime", "resting_hr", "hrv_rmssd_ms",
        "stress_score", "steps", "active_minutes",
    ))


# ── normalize_records / normalize_profile ────────────────────────────────────


def test_normalize_records_preserves_order():
    raws = [_base_raw(date="2026-06-01"), _base_raw(date="2026-06-02")]
    records = normalize_records(raws)
    assert records[0].date == date(2026, 6, 1)
    assert records[1].date == date(2026, 6, 2)


def test_normalize_profile_sorts_records():
    raw_profile = {
        "user_id": "u1",
        "age": 30,
        "gender": "Female",
        "records": [_base_raw(date="2026-06-03"), _base_raw(date="2026-06-01"), _base_raw(date="2026-06-02")],
    }
    profile = normalize_profile(raw_profile)
    assert profile.user_id == "u1"
    assert profile.age == 30
    dates = [r.date for r in profile.records]
    assert dates == sorted(dates)


def test_normalize_profile_roundtrips_synthetic():
    """A synthetic profile should pass normalization without any missing/invalid fields."""
    from wearable_insights.data.synthetic import build_recovery_deficit_snapshot
    raw = build_recovery_deficit_snapshot(days=5)
    profile = normalize_profile(raw)
    for rec in profile.records:
        assert rec.missing_fields == [], f"unexpected missing on {rec.date}: {rec.missing_fields}"
        assert rec.invalid_fields == [], f"unexpected invalid on {rec.date}: {rec.invalid_fields}"


# ── missing_fields ordering ───────────────────────────────────────────────────


def test_missing_fields_follow_canonical_order():
    raw = _base_raw(steps=None, sleep_score=None, hrv_rmssd_ms=None)
    rec = normalize_record(raw)
    expected_order = ["sleep_score", "hrv_rmssd_ms", "steps"]
    assert rec.missing_fields == expected_order
