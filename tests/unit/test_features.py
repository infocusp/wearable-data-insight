"""Unit tests for features.py (FR-006)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from wearable_insights.features import compute_features, _bedtime_to_minutes, DerivedFeatures
from wearable_insights.models import CanonicalDailyRecord


# ── Helpers ───────────────────────────────────────────────────────────────────

def _record(
    d: str,
    *,
    sleep_duration_minutes: int | None = 420,
    deep_sleep_minutes: int | None = 80,
    rem_sleep_minutes: int | None = 90,
    bedtime: str | None = "22:30",
    **kwargs,
) -> CanonicalDailyRecord:
    return CanonicalDailyRecord(
        user_id="u1",
        date=date.fromisoformat(d),
        sleep_duration_minutes=sleep_duration_minutes,
        deep_sleep_minutes=deep_sleep_minutes,
        rem_sleep_minutes=rem_sleep_minutes,
        bedtime=bedtime,
        **kwargs,
    )


def _history(n_days: int, analysis_date: date, bedtime: str = "22:30") -> list[CanonicalDailyRecord]:
    return [
        _record(
            (analysis_date - timedelta(days=n_days - i)).isoformat(),
            bedtime=bedtime,
        )
        for i in range(n_days + 1)
    ]


# ── sleep_stage_ratio ─────────────────────────────────────────────────────────


def test_stage_ratio_computed_correctly():
    records = [_record("2026-06-10", deep_sleep_minutes=84, rem_sleep_minutes=126, sleep_duration_minutes=420)]
    feat = compute_features(records, date(2026, 6, 10))
    # (84 + 126) / 420 = 0.5
    assert feat.sleep_stage_ratio == pytest.approx(0.5, abs=0.001)


def test_stage_ratio_null_when_duration_missing():
    records = [_record("2026-06-10", sleep_duration_minutes=None)]
    feat = compute_features(records, date(2026, 6, 10))
    assert feat.sleep_stage_ratio is None


def test_stage_ratio_null_when_deep_missing():
    records = [_record("2026-06-10", deep_sleep_minutes=None)]
    feat = compute_features(records, date(2026, 6, 10))
    assert feat.sleep_stage_ratio is None


def test_stage_ratio_zero_duration_gives_null():
    records = [_record("2026-06-10", sleep_duration_minutes=0, deep_sleep_minutes=0, rem_sleep_minutes=0)]
    feat = compute_features(records, date(2026, 6, 10))
    assert feat.sleep_stage_ratio is None


# ── bedtime_shift_minutes ─────────────────────────────────────────────────────


def test_bedtime_shift_zero_when_consistent():
    analysis = date(2026, 6, 10)
    records = _history(7, analysis, bedtime="22:30")
    feat = compute_features(records, analysis)
    assert feat.bedtime_shift_minutes == pytest.approx(0.0, abs=0.5)


def test_bedtime_shift_positive_when_later_than_usual():
    analysis = date(2026, 6, 10)
    prior = [_record((analysis - timedelta(days=i)).isoformat(), bedtime="22:00") for i in range(1, 8)]
    current = _record(analysis.isoformat(), bedtime="23:00")
    records = prior + [current]
    feat = compute_features(records, analysis)
    assert feat.bedtime_shift_minutes == pytest.approx(60.0, abs=1.0)


def test_bedtime_shift_negative_when_earlier_than_usual():
    analysis = date(2026, 6, 10)
    prior = [_record((analysis - timedelta(days=i)).isoformat(), bedtime="23:30") for i in range(1, 8)]
    current = _record(analysis.isoformat(), bedtime="22:00")
    records = prior + [current]
    feat = compute_features(records, analysis)
    assert feat.bedtime_shift_minutes == pytest.approx(-90.0, abs=1.0)


def test_bedtime_shift_null_when_no_prior_data():
    records = [_record("2026-06-10")]
    feat = compute_features(records, date(2026, 6, 10))
    assert feat.bedtime_shift_minutes is None


def test_bedtime_shift_null_when_current_bedtime_missing():
    analysis = date(2026, 6, 10)
    prior = [_record((analysis - timedelta(days=i)).isoformat()) for i in range(1, 5)]
    current = _record(analysis.isoformat(), bedtime=None)
    feat = compute_features(prior + [current], analysis)
    assert feat.bedtime_shift_minutes is None


def test_bedtime_shift_handles_midnight_crossing():
    """23:50 → 00:10 is a +20 minute shift, not −1420."""
    analysis = date(2026, 6, 10)
    prior = [_record((analysis - timedelta(days=i)).isoformat(), bedtime="23:50") for i in range(1, 8)]
    current = _record(analysis.isoformat(), bedtime="00:10")
    feat = compute_features(prior + [current], analysis)
    # 00:10 → 24*60+10=1450; 23:50 → 23*60+50=1430; shift = +20
    assert feat.bedtime_shift_minutes == pytest.approx(20.0, abs=1.0)


# ── sleep_consistency_score ───────────────────────────────────────────────────


def test_consistency_high_when_stable():
    analysis = date(2026, 6, 10)
    records = _history(7, analysis, bedtime="22:30")
    feat = compute_features(records, analysis)
    assert feat.sleep_consistency_score is not None
    assert feat.sleep_consistency_score >= 0.95


def test_consistency_lower_when_variable():
    analysis = date(2026, 6, 10)
    bedtimes = ["22:00", "23:00", "22:30", "00:00", "21:30", "23:30", "22:00", "22:45"]
    records = [
        _record((analysis - timedelta(days=len(bedtimes) - 1 - i)).isoformat(), bedtime=bt)
        for i, bt in enumerate(bedtimes)
    ]
    feat = compute_features(records, analysis)
    assert feat.sleep_consistency_score is not None
    assert feat.sleep_consistency_score < 0.8


def test_consistency_null_with_fewer_than_3_bedtimes():
    records = [
        _record("2026-06-09"),
        _record("2026-06-10"),
    ]
    feat = compute_features(records, date(2026, 6, 10))
    assert feat.sleep_consistency_score is None


def test_consistency_clamped_to_zero_for_extreme_variation():
    analysis = date(2026, 6, 10)
    # std > 60 min → score should be 0.0 (clamped, not negative)
    bedtimes = ["20:00", "23:59", "20:00", "23:59", "20:00", "23:59", "20:00", "23:59"]
    records = [
        _record((analysis - timedelta(days=len(bedtimes) - 1 - i)).isoformat(), bedtime=bt)
        for i, bt in enumerate(bedtimes)
    ]
    feat = compute_features(records, analysis)
    assert feat.sleep_consistency_score is not None
    assert feat.sleep_consistency_score >= 0.0


# ── No current-day record ─────────────────────────────────────────────────────


def test_returns_empty_features_when_no_current_record():
    records = [_record("2026-06-09")]
    feat = compute_features(records, date(2026, 6, 10))
    assert feat == DerivedFeatures()


# ── _bedtime_to_minutes helper ────────────────────────────────────────────────


def test_bedtime_to_minutes_standard():
    assert _bedtime_to_minutes("22:30") == 22 * 60 + 30


def test_bedtime_to_minutes_post_midnight():
    # 00:30 treated as 24*60 + 30 = 1470 (avoids negative shifts vs 23:xx)
    assert _bedtime_to_minutes("00:30") == 24 * 60 + 30


def test_bedtime_to_minutes_none():
    assert _bedtime_to_minutes(None) is None
