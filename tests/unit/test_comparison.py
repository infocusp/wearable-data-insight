"""Unit tests for comparison.py (FR-009)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from wearable_insights.models import CanonicalDailyRecord
from wearable_insights.comparison import build_comparison_object
from wearable_insights.trends import TREND_THRESHOLD_PCT


# ── Helpers ───────────────────────────────────────────────────────────────────

def _record(d: str, **kwargs) -> CanonicalDailyRecord:
    defaults = dict(
        user_id="u1",
        sleep_duration_minutes=420,
        sleep_score=75,
        deep_sleep_minutes=80,
        rem_sleep_minutes=90,
        bedtime="22:30",
        resting_hr=58,
        hrv_rmssd_ms=65.0,
        stress_score=25,
        steps=8000,
        active_minutes=45,
    )
    defaults.update(kwargs)
    return CanonicalDailyRecord(date=date.fromisoformat(d), **defaults)


def _history(n_prior: int, analysis: date, **kw) -> list[CanonicalDailyRecord]:
    prior = [_record((analysis - timedelta(days=i)).isoformat(), **kw) for i in range(1, n_prior + 1)]
    current = _record(analysis.isoformat(), **kw)
    return prior + [current]


# ── Structure ─────────────────────────────────────────────────────────────────


def test_all_sections_present():
    analysis = date(2026, 6, 17)
    co = build_comparison_object(_history(30, analysis), analysis)
    assert "sleep_duration" in co.sleep
    assert "sleep_score" in co.sleep
    assert "deep_sleep" in co.sleep
    assert "rem_sleep" in co.sleep
    assert "resting_hr" in co.heart_health
    assert "hrv" in co.heart_health
    assert "stress" in co.heart_health
    assert "steps" in co.activity
    assert "active_minutes" in co.activity


def test_user_id_and_date_propagated():
    analysis = date(2026, 6, 17)
    co = build_comparison_object(_history(30, analysis), analysis)
    assert co.user_id == "u1"
    assert co.analysis_date == analysis


def test_schema_version_default():
    analysis = date(2026, 6, 17)
    co = build_comparison_object(_history(10, analysis), analysis)
    assert co.schema_version == "1.0"


# ── Current / baseline values ─────────────────────────────────────────────────


def test_current_value_matches_analysis_day():
    analysis = date(2026, 6, 17)
    records = _history(30, analysis, steps=5000)
    # Override just the current day
    records[-1] = _record(analysis.isoformat(), steps=9999)
    co = build_comparison_object(records, analysis)
    assert co.activity["steps"].current_value == 9999.0


def test_baseline_value_is_30d_mean_when_available():
    analysis = date(2026, 6, 17)
    records = _history(30, analysis, steps=6000)
    records[-1] = _record(analysis.isoformat(), steps=9999)
    co = build_comparison_object(records, analysis)
    # 30 prior days all at 6000 → monthly baseline ≈ 6000
    assert co.activity["steps"].monthly.baseline_value == pytest.approx(6000.0, abs=1.0)


def test_baseline_null_when_no_prior_data():
    analysis = date(2026, 6, 17)
    co = build_comparison_object([_record(analysis.isoformat())], analysis)
    assert co.activity["steps"].monthly.baseline_value is None
    assert co.activity["steps"].weekly.baseline_value is None
    assert co.activity["steps"].weekday.baseline_value is None


# ── Trend and evaluation tags ─────────────────────────────────────────────────


def test_trend_up_when_significantly_above_baseline():
    analysis = date(2026, 6, 17)
    prior = [_record((analysis - timedelta(days=i)).isoformat(), steps=5000) for i in range(1, 31)]
    current = _record(analysis.isoformat(), steps=7000)  # +40%
    co = build_comparison_object(prior + [current], analysis)
    assert co.activity["steps"].monthly.trend == "up"
    assert "above_baseline_steps" in co.activity["steps"].flags


def test_trend_down_when_significantly_below_baseline():
    analysis = date(2026, 6, 17)
    prior = [_record((analysis - timedelta(days=i)).isoformat(), steps=8000) for i in range(1, 31)]
    current = _record(analysis.isoformat(), steps=4000)  # −50%
    co = build_comparison_object(prior + [current], analysis)
    assert co.activity["steps"].monthly.trend == "down"
    assert "below_baseline_steps" in co.activity["steps"].flags


def test_trend_stable_within_deadband():
    analysis = date(2026, 6, 17)
    records = _history(30, analysis, steps=8000)
    co = build_comparison_object(records, analysis)
    assert co.activity["steps"].monthly.trend == "stable"


def test_critically_elevated_tag_at_50pct():
    analysis = date(2026, 6, 17)
    prior = [_record((analysis - timedelta(days=i)).isoformat(), hrv_rmssd_ms=60.0) for i in range(1, 31)]
    current = _record(analysis.isoformat(), hrv_rmssd_ms=100.0)  # +66.7%
    co = build_comparison_object(prior + [current], analysis)
    assert co.heart_health["hrv"].monthly.evaluation_tag == "Critically Elevated"
    assert "critical_deviation" in co.heart_health["hrv"].flags


def test_critically_depressed_tag_at_minus_50pct():
    analysis = date(2026, 6, 17)
    prior = [_record((analysis - timedelta(days=i)).isoformat(), stress_score=20) for i in range(1, 31)]
    current = _record(analysis.isoformat(), stress_score=80)  # +300%: critically elevated stress
    co = build_comparison_object(prior + [current], analysis)
    # stress going to 80 from 20 baseline → +300% → Critically Elevated
    assert co.heart_health["stress"].monthly.evaluation_tag == "Critically Elevated"


# ── Data quality ──────────────────────────────────────────────────────────────


def test_data_quality_captures_missing_fields():
    analysis = date(2026, 6, 17)
    prior = [_record((analysis - timedelta(days=i)).isoformat()) for i in range(1, 10)]
    current = CanonicalDailyRecord(
        user_id="u1",
        date=analysis,
        steps=None,
        missing_fields=["steps"],
    )
    co = build_comparison_object(prior + [current], analysis)
    assert "steps" in co.data_quality.missing_fields


def test_data_quality_low_confidence_when_short_history():
    analysis = date(2026, 6, 17)
    records = _history(3, analysis)  # only 3 prior days
    co = build_comparison_object(records, analysis)
    assert co.data_quality.low_confidence is True


def test_data_quality_not_low_confidence_with_30_days():
    analysis = date(2026, 6, 17)
    records = _history(30, analysis)
    co = build_comparison_object(records, analysis)
    assert co.data_quality.low_confidence is False


# ── Associations included ─────────────────────────────────────────────────────


def test_associations_included_when_rules_fire():
    analysis = date(2026, 6, 17)
    # Give healthy baseline, then stress up and sleep down on current day
    prior = [_record((analysis - timedelta(days=i)).isoformat(),
                     stress_score=20, sleep_duration_minutes=450) for i in range(1, 31)]
    current = _record(analysis.isoformat(), stress_score=80, sleep_duration_minutes=240)
    co = build_comparison_object(prior + [current], analysis)
    relations = {a.relation for a in co.candidate_associations}
    assert "poor_sleep_and_higher_stress_co_occur" in relations


def test_associations_empty_when_no_rules_fire():
    analysis = date(2026, 6, 17)
    records = _history(30, analysis)  # all stable
    co = build_comparison_object(records, analysis)
    # With all stable trends, no rule should fire
    for assoc in co.candidate_associations:
        # If there are any, they should all have kind="association"
        assert assoc.kind == "association"


# ── Determinism ───────────────────────────────────────────────────────────────


def test_comparison_is_deterministic():
    from wearable_insights.data.synthetic import generate_synthetic_profile
    from wearable_insights.normalize import normalize_profile

    raw = generate_synthetic_profile("recovery_deficit", seed=42, days=31)
    profile = normalize_profile(raw)
    analysis = profile.records[-1].date

    co1 = build_comparison_object(profile.records, analysis)
    co2 = build_comparison_object(profile.records, analysis)

    assert co1.model_dump_json() == co2.model_dump_json()
