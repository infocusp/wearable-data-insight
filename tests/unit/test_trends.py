"""Unit tests for trends.py (FR-007, FR-008)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from wearable_insights.models import CanonicalDailyRecord
from wearable_insights.trends import (
    LOW_CONFIDENCE_MIN_DAYS,
    TREND_THRESHOLD_PCT,
    compute_baselines,
    evaluation_tag,
    percentage_change,
    trend_label,
    choose_baseline,
    TRACKED_METRICS,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _record(d: str, **kwargs) -> CanonicalDailyRecord:
    defaults = {
        "user_id": "u1",
        "sleep_duration_minutes": 420,
        "sleep_score": 75,
        "deep_sleep_minutes": 80,
        "rem_sleep_minutes": 90,
        "bedtime": "22:30",
        "resting_hr": 58,
        "hrv_rmssd_ms": 65.0,
        "stress_score": 25,
        "steps": 8000,
        "active_minutes": 45,
    }
    defaults.update(kwargs)
    return CanonicalDailyRecord(date=date.fromisoformat(d), **defaults)


def _build_history(
    n_prior: int,
    analysis_date: date,
    **daily_overrides,
) -> list[CanonicalDailyRecord]:
    """n_prior prior records + one current-day record."""
    records = [
        _record((analysis_date - timedelta(days=n_prior - i)).isoformat(), **daily_overrides)
        for i in range(n_prior)
    ]
    records.append(_record(analysis_date.isoformat(), **daily_overrides))
    return records


# ── percentage_change ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("current,baseline,expected", [
    (110, 100, 10.0),
    (90, 100, -10.0),
    (100, 100, 0.0),
    (150, 100, 50.0),
    (50, 100, -50.0),
])
def test_percentage_change_values(current, baseline, expected):
    assert percentage_change(current, baseline) == pytest.approx(expected, abs=0.01)


def test_percentage_change_null_when_baseline_zero():
    assert percentage_change(100, 0) is None


def test_percentage_change_null_when_current_none():
    assert percentage_change(None, 100) is None


def test_percentage_change_null_when_baseline_none():
    assert percentage_change(100, None) is None


def test_percentage_change_rounded_to_1dp():
    result = percentage_change(103, 100)
    assert result == 3.0


# ── trend_label ───────────────────────────────────────────────────────────────


def test_trend_up_above_threshold():
    assert trend_label(TREND_THRESHOLD_PCT + 0.1) == "up"


def test_trend_down_below_threshold():
    assert trend_label(-(TREND_THRESHOLD_PCT + 0.1)) == "down"


def test_trend_stable_within_band():
    assert trend_label(0.0) == "stable"
    assert trend_label(TREND_THRESHOLD_PCT) == "stable"
    assert trend_label(-TREND_THRESHOLD_PCT) == "stable"


def test_trend_stable_when_pct_none():
    assert trend_label(None) == "stable"


def test_trend_exactly_at_boundary():
    assert trend_label(15.0) == "stable"
    assert trend_label(15.1) == "up"
    assert trend_label(-15.0) == "stable"
    assert trend_label(-15.1) == "down"


# ── evaluation_tag ────────────────────────────────────────────────────────────


def test_evaluation_tag_stable():
    assert evaluation_tag(0.0) == "Stable / Within Normal Baseline"
    assert evaluation_tag(15.0) == "Stable / Within Normal Baseline"
    assert evaluation_tag(-15.0) == "Stable / Within Normal Baseline"
    assert evaluation_tag(None) == "Stable / Within Normal Baseline"


def test_evaluation_tag_significantly_elevated():
    assert evaluation_tag(30.0) == "Significantly Elevated"
    assert evaluation_tag(49.9) == "Significantly Elevated"


def test_evaluation_tag_significantly_depressed():
    assert evaluation_tag(-30.0) == "Significantly Depressed"
    assert evaluation_tag(-49.9) == "Significantly Depressed"


def test_evaluation_tag_critically_elevated():
    assert evaluation_tag(50.0) == "Critically Elevated"
    assert evaluation_tag(100.0) == "Critically Elevated"


def test_evaluation_tag_critically_depressed():
    assert evaluation_tag(-50.0) == "Critically Depressed"
    assert evaluation_tag(-100.0) == "Critically Depressed"


# ── compute_baselines – basic ─────────────────────────────────────────────────


def test_baselines_produced_for_all_tracked_metrics():
    analysis = date(2026, 6, 17)
    records = _build_history(30, analysis)
    bs = compute_baselines(records, analysis)
    tracked_names = {name for name, _ in TRACKED_METRICS}
    assert set(bs.metrics.keys()) == tracked_names


def test_current_value_captured():
    analysis = date(2026, 6, 17)
    records = _build_history(10, analysis, steps=9999)
    bs = compute_baselines(records, analysis)
    assert bs.metrics["steps"].current == 9999.0


def test_7d_mean_computed_from_prior_days_only():
    analysis = date(2026, 6, 17)
    prior = [_record((analysis - timedelta(days=i)).isoformat(), steps=1000) for i in range(1, 8)]
    current = _record(analysis.isoformat(), steps=9999)
    bs = compute_baselines(prior + [current], analysis)
    assert bs.metrics["steps"].mean_7d == pytest.approx(1000.0, abs=0.1)


def test_30d_mean_excludes_current_day():
    analysis = date(2026, 6, 17)
    prior = [_record((analysis - timedelta(days=i)).isoformat(), steps=2000) for i in range(1, 31)]
    current = _record(analysis.isoformat(), steps=9999)
    bs = compute_baselines(prior + [current], analysis)
    assert bs.metrics["steps"].mean_30d == pytest.approx(2000.0, abs=0.1)


def test_weekday_mean_uses_only_same_weekday():
    analysis = date(2026, 6, 17)  # Wednesday
    records = []
    for i in range(1, 60):
        d = analysis - timedelta(days=i)
        steps = 5000 if d.weekday() == analysis.weekday() else 10000
        records.append(_record(d.isoformat(), steps=steps))
    records.append(_record(analysis.isoformat(), steps=7000))
    bs = compute_baselines(records, analysis)
    # Only same-weekday prior days (steps=5000) should feed weekday_mean
    assert bs.metrics["steps"].weekday_mean == pytest.approx(5000.0, abs=1.0)


# ── compute_baselines – rounding ──────────────────────────────────────────────


def test_int_round_metrics_rounded_to_integer():
    analysis = date(2026, 6, 17)
    # 5 priors with steps values that average to a non-integer
    steps_vals = [8001, 8002, 8003, 8004, 8005]
    prior = [_record((analysis - timedelta(days=i)).isoformat(), steps=s)
             for i, s in enumerate(steps_vals, start=1)]
    current = _record(analysis.isoformat(), steps=8500)
    bs = compute_baselines(prior + [current], analysis)
    mean = bs.metrics["steps"].mean_7d
    assert mean is not None
    assert mean == float(round(sum(steps_vals) / len(steps_vals)))


def test_float_metric_rounded_to_1dp():
    analysis = date(2026, 6, 17)
    prior = [_record((analysis - timedelta(days=i)).isoformat(), hrv_rmssd_ms=62.33)
             for i in range(1, 8)]
    current = _record(analysis.isoformat())
    bs = compute_baselines(prior + [current], analysis)
    assert bs.metrics["hrv"].mean_7d == pytest.approx(62.3, abs=0.05)


# ── compute_baselines – low confidence ───────────────────────────────────────


def test_low_confidence_when_fewer_than_7_prior_days():
    analysis = date(2026, 6, 17)
    records = _build_history(4, analysis)  # 4 prior days
    bs = compute_baselines(records, analysis)
    for mb in bs.metrics.values():
        assert mb.low_confidence is True


def test_high_confidence_when_30_or_more_prior_days():
    analysis = date(2026, 6, 17)
    records = _build_history(30, analysis)
    bs = compute_baselines(records, analysis)
    for mb in bs.metrics.values():
        assert mb.low_confidence is False


def test_low_confidence_when_metric_always_null():
    analysis = date(2026, 6, 17)
    prior = [_record((analysis - timedelta(days=i)).isoformat(), hrv_rmssd_ms=None)
             for i in range(1, 31)]
    current = _record(analysis.isoformat(), hrv_rmssd_ms=None)
    bs = compute_baselines(prior + [current], analysis)
    hrv = bs.metrics["hrv"]
    assert hrv.mean_30d is None
    assert hrv.low_confidence is True


def test_n_days_used_counts_non_null_values():
    analysis = date(2026, 6, 17)
    # 20 prior days with valid steps, 10 with null
    prior_valid = [_record((analysis - timedelta(days=i)).isoformat(), steps=8000)
                   for i in range(1, 21)]
    prior_null = [_record((analysis - timedelta(days=i)).isoformat(), steps=None)
                  for i in range(21, 31)]
    current = _record(analysis.isoformat())
    bs = compute_baselines(prior_valid + prior_null + [current], analysis)
    assert bs.metrics["steps"].n_days_used == 20


# ── compute_baselines – edge cases ────────────────────────────────────────────


def test_no_prior_records_all_baselines_null():
    analysis = date(2026, 6, 17)
    records = [_record(analysis.isoformat())]
    bs = compute_baselines(records, analysis)
    for mb in bs.metrics.values():
        assert mb.mean_7d is None
        assert mb.mean_30d is None
        assert mb.low_confidence is True


def test_no_current_record_current_is_null():
    analysis = date(2026, 6, 17)
    prior = [_record((analysis - timedelta(days=i)).isoformat()) for i in range(1, 10)]
    bs = compute_baselines(prior, analysis)
    for mb in bs.metrics.values():
        assert mb.current is None


def test_unsorted_records_produce_correct_baselines():
    analysis = date(2026, 6, 10)
    records = _build_history(20, analysis, steps=6000)
    import random
    rng = random.Random(0)
    rng.shuffle(records)
    bs = compute_baselines(records, analysis)
    assert bs.metrics["steps"].mean_30d == pytest.approx(6000.0, abs=1.0)


# ── choose_baseline ───────────────────────────────────────────────────────────


def test_choose_baseline_prefers_30d():
    from wearable_insights.models import MetricBaseline
    mb = MetricBaseline(mean_7d=100.0, mean_30d=200.0)
    assert choose_baseline(mb) == 200.0


def test_choose_baseline_falls_back_to_7d():
    from wearable_insights.models import MetricBaseline
    mb = MetricBaseline(mean_7d=100.0, mean_30d=None)
    assert choose_baseline(mb) == 100.0


def test_choose_baseline_returns_none_when_both_null():
    from wearable_insights.models import MetricBaseline
    mb = MetricBaseline(mean_7d=None, mean_30d=None)
    assert choose_baseline(mb) is None


# ── Determinism ───────────────────────────────────────────────────────────────


def test_compute_baselines_deterministic():
    """Same inputs must always produce byte-identical results (SC-006)."""
    from wearable_insights.data.synthetic import generate_synthetic_profile
    from wearable_insights.normalize import normalize_profile

    raw = generate_synthetic_profile("healthy_consistent", seed=42, days=45)
    profile = normalize_profile(raw)
    analysis = profile.records[-1].date

    bs1 = compute_baselines(profile.records, analysis)
    bs2 = compute_baselines(profile.records, analysis)

    for metric_name in bs1.metrics:
        m1 = bs1.metrics[metric_name]
        m2 = bs2.metrics[metric_name]
        assert m1.mean_30d == m2.mean_30d, f"30d mean differs for {metric_name}"
        assert m1.mean_7d == m2.mean_7d, f"7d mean differs for {metric_name}"
