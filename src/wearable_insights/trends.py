"""Personal baselines and trend labels for wearable metrics (FR-007, FR-008).

Each tracked metric gets a MetricBaseline containing:
  - current          The value on analysis_date (null if no record / metric absent).
  - mean_7d          Mean of the up-to-7 prior calendar days (non-null values only).
  - mean_30d         Mean of the up-to-30 prior calendar days.
  - weekday_mean     Mean of prior days sharing the same day-of-week.
  - n_days_used      Count of non-null values that fed the 30-day mean.
  - low_confidence   True when n_days_used < 7 or the 30-day baseline is undefined.

Trend labels (±15% dead-band, FR-008):
  up     percentage_change > +15%
  down   percentage_change < -15%
  stable  |percentage_change| ≤ 15%  (also used when baseline is null)

Evaluation tags map percentage_change magnitude:
  Critically Elevated / Depressed  |Δ| ≥ 50%
  Significantly Elevated / Depressed  15% < |Δ| < 50%
  Stable / Within Normal Baseline  |Δ| ≤ 15% or baseline null
"""

from __future__ import annotations

import statistics
from datetime import date
from typing import Literal

from .models import BaselineSet, CanonicalDailyRecord, MetricBaseline


# ── Tracked metrics ───────────────────────────────────────────────────────────
# (baseline_name, CanonicalDailyRecord attribute)

TRACKED_METRICS: list[tuple[str, str]] = [
    ("sleep_duration", "sleep_duration_minutes"),
    ("sleep_score", "sleep_score"),
    ("deep_sleep", "deep_sleep_minutes"),
    ("rem_sleep", "rem_sleep_minutes"),
    ("resting_hr", "resting_hr"),
    ("hrv", "hrv_rmssd_ms"),
    ("stress", "stress_score"),
    ("steps", "steps"),
    ("active_minutes", "active_minutes"),
]

# Metrics whose mean is rounded to the nearest integer (as opposed to 1 d.p.)
_INT_ROUND_METRICS: frozenset[str] = frozenset(
    {"sleep_score", "resting_hr", "stress", "steps"}
)

# ── Thresholds ────────────────────────────────────────────────────────────────

TREND_THRESHOLD_PCT: float = 15.0   # dead-band: ±15 %
CRITICAL_THRESHOLD_PCT: float = 50.0  # critically elevated/depressed threshold
LOW_CONFIDENCE_MIN_DAYS: int = 7     # fewer history days → low_confidence = True
WEEKDAY_WINDOW_DAYS: int = 90        # lookback cap for same-weekday baseline


# ── Internal helpers ──────────────────────────────────────────────────────────


def _extract(record: CanonicalDailyRecord, attr: str) -> float | None:
    val = getattr(record, attr, None)
    return float(val) if val is not None else None


def _safe_mean(values: list[float]) -> float | None:
    return statistics.mean(values) if values else None


def _round_mean(metric_name: str, value: float | None) -> float | None:
    if value is None:
        return None
    if metric_name in _INT_ROUND_METRICS:
        return float(round(value))
    return round(value, 1)


# ── Public utility functions ──────────────────────────────────────────────────


def percentage_change(
    current: float | None,
    baseline: float | None,
) -> float | None:
    """Signed percentage change of *current* relative to *baseline*.

    Returns None when either input is None or baseline is zero
    (avoids division-by-zero; treated as undefined / low-confidence).
    Rounded to 1 decimal place.
    """
    if current is None or baseline is None or baseline == 0:
        return None
    return round((current - baseline) / abs(baseline) * 100, 1)


def trend_label(
    pct_change: float | None,
    threshold_pct: float = TREND_THRESHOLD_PCT,
) -> Literal["up", "down", "stable"]:
    """Derive the trend direction from a signed percentage change.

    When pct_change is None (undefined baseline) → 'stable'.
    """
    if pct_change is None:
        return "stable"
    if pct_change > threshold_pct:
        return "up"
    if pct_change < -threshold_pct:
        return "down"
    return "stable"


def evaluation_tag(
    pct_change: float | None,
) -> Literal[
    "Significantly Elevated",
    "Significantly Depressed",
    "Critically Elevated",
    "Critically Depressed",
    "Stable / Within Normal Baseline",
]:
    """Map a signed percentage change to an evaluation tag.

    None or within ±TREND_THRESHOLD_PCT → 'Stable / Within Normal Baseline'.
    """
    if pct_change is None or abs(pct_change) <= TREND_THRESHOLD_PCT:
        return "Stable / Within Normal Baseline"
    if pct_change >= CRITICAL_THRESHOLD_PCT:
        return "Critically Elevated"
    if pct_change <= -CRITICAL_THRESHOLD_PCT:
        return "Critically Depressed"
    if pct_change > TREND_THRESHOLD_PCT:
        return "Significantly Elevated"
    return "Significantly Depressed"


def choose_baseline(baseline: MetricBaseline) -> float | None:
    """Select the best available baseline value (30d preferred, 7d fallback)."""
    if baseline.mean_30d is not None:
        return baseline.mean_30d
    return baseline.mean_7d


# ── Core computation ──────────────────────────────────────────────────────────


def compute_baselines(
    records: list[CanonicalDailyRecord],
    analysis_date: date,
) -> BaselineSet:
    """Build a BaselineSet for *analysis_date* from the full record history.

    Prior records (date < analysis_date) feed the 7d/30d/weekday windows.
    The current day's value is captured in MetricBaseline.current.
    Records need not be pre-sorted.
    """
    sorted_records = sorted(records, key=lambda r: r.date)
    current_record = next(
        (r for r in sorted_records if r.date == analysis_date), None
    )
    prior = [r for r in sorted_records if r.date < analysis_date]

    analysis_weekday = analysis_date.weekday()
    prior_7 = prior[-7:]
    prior_30 = prior[-30:]
    prior_60 = prior[-60:]
    prior_90 = prior[-90:]
    prior_same_weekday = [
        r for r in prior[-WEEKDAY_WINDOW_DAYS:] if r.date.weekday() == analysis_weekday
    ]

    user_id = (
        current_record.user_id
        if current_record
        else (prior[-1].user_id if prior else "")
    )

    metrics: dict[str, MetricBaseline] = {}

    for metric_name, attr in TRACKED_METRICS:
        current_val = _extract(current_record, attr) if current_record else None

        vals_7 = [v for r in prior_7 if (v := _extract(r, attr)) is not None]
        vals_30 = [v for r in prior_30 if (v := _extract(r, attr)) is not None]
        vals_60 = [v for r in prior_60 if (v := _extract(r, attr)) is not None]
        vals_90 = [v for r in prior_90 if (v := _extract(r, attr)) is not None]
        vals_weekday = [
            v for r in prior_same_weekday if (v := _extract(r, attr)) is not None
        ]

        raw_mean_7d = _safe_mean(vals_7)
        raw_mean_30d = _safe_mean(vals_30)
        raw_mean_60d = _safe_mean(vals_60)
        raw_mean_90d = _safe_mean(vals_90)
        raw_weekday_mean = _safe_mean(vals_weekday)

        n_used = len(vals_30)
        low_conf = n_used < LOW_CONFIDENCE_MIN_DAYS or raw_mean_30d is None

        metrics[metric_name] = MetricBaseline(
            current=current_val,
            mean_7d=_round_mean(metric_name, raw_mean_7d),
            mean_30d=_round_mean(metric_name, raw_mean_30d),
            mean_60d=_round_mean(metric_name, raw_mean_60d),
            mean_90d=_round_mean(metric_name, raw_mean_90d),
            weekday_mean=_round_mean(metric_name, raw_weekday_mean),
            n_days_used=n_used,
            low_confidence=low_conf,
        )

    return BaselineSet(
        user_id=user_id,
        analysis_date=analysis_date,
        metrics=metrics,
    )
