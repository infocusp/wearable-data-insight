"""Assemble the ComparisonObject from a record history (FR-009).

Single public entry point::

    comparison = build_comparison_object(records, analysis_date)

Internally this calls:

1. trends.compute_baselines  → BaselineSet (7d / 30d / weekday means)
2. features.compute_features → DerivedFeatures (stage ratio, bedtime shift,
                                consistency; used to generate extra flags)
3. associations.compute_associations → CandidateAssociation[] (R1/R2/R3 rules)

The LLM receives *only* the ComparisonObject — never raw daily tables (Principle I).
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from .associations import compute_associations
from .features import compute_features
from .models import (
    CanonicalDailyRecord,
    CandidateAssociation,
    ComparisonObject,
    DataQuality,
    MetricBaseline,
    MetricComparison,
    WindowComparison,
)
from .trends import (
    compute_baselines,
    evaluation_tag,
    percentage_change,
    trend_label,
)


# ── Metric groupings (matches ComparisonObject sections) ─────────────────────

_SLEEP_METRICS: tuple[str, ...] = (
    "sleep_duration",
    "sleep_score",
    "deep_sleep",
    "rem_sleep",
)

_HEART_HEALTH_METRICS: tuple[str, ...] = (
    "resting_hr",
    "hrv",
    "stress",
)

_ACTIVITY_METRICS: tuple[str, ...] = (
    "steps",
    "active_minutes",
)


# ── Derived-feature flag thresholds ──────────────────────────────────────────

_BEDTIME_SHIFT_FLAG_MIN: float = 30.0    # > 30 min later → flag
_CONSISTENCY_LOW_THRESHOLD: float = 0.60  # < 0.60 → flag


# ── Internal helpers ──────────────────────────────────────────────────────────


def _build_flags(metric_name: str, ev_tag: str) -> list[str]:
    """Generate descriptive flag strings from the primary (monthly) evaluation tag."""
    flags: list[str] = []
    if "Depressed" in ev_tag:
        flags.append(f"below_baseline_{metric_name}")
    if "Elevated" in ev_tag:
        flags.append(f"above_baseline_{metric_name}")
    if "Critical" in ev_tag:
        flags.append("critical_deviation")
    return flags


def _build_window(current: float | None, baseline_val: float | None) -> WindowComparison:
    pct = percentage_change(current, baseline_val)
    return WindowComparison(
        baseline_value=baseline_val,
        percentage_change=pct,
        trend=trend_label(pct),
        evaluation_tag=evaluation_tag(pct),
    )


def _build_metric_comparison(mb: MetricBaseline, metric_name: str) -> MetricComparison:
    current = mb.current
    monthly = _build_window(current, mb.mean_30d)
    weekly = _build_window(current, mb.mean_7d)
    weekday = _build_window(current, mb.weekday_mean)
    sixty_day = _build_window(current, mb.mean_60d)
    ninety_day = _build_window(current, mb.mean_90d)
    # Flags derived from the monthly window; fall back to weekly when no 30d data
    primary = monthly if mb.mean_30d is not None else weekly
    flags = _build_flags(metric_name, primary.evaluation_tag)
    return MetricComparison(
        current_value=current,
        weekly=weekly,
        monthly=monthly,
        weekday=weekday,
        sixty_day=sixty_day,
        ninety_day=ninety_day,
        flags=flags,
    )


def _build_section(
    metric_names: tuple[str, ...],
    all_baselines: dict[str, MetricBaseline],
) -> dict[str, MetricComparison]:
    return {
        name: _build_metric_comparison(mb, name)
        for name in metric_names
        if (mb := all_baselines.get(name)) is not None
    }


def _enrich_sleep_flags(
    sleep_section: dict[str, MetricComparison],
    bedtime_shift: float | None,
    consistency_score: float | None,
) -> dict[str, MetricComparison]:
    """Add derived-feature flags to the sleep_duration comparison entry."""
    if "sleep_duration" not in sleep_section:
        return sleep_section

    extra: list[str] = []
    if bedtime_shift is not None and abs(bedtime_shift) > _BEDTIME_SHIFT_FLAG_MIN:
        direction = "later" if bedtime_shift > 0 else "earlier"
        extra.append(f"bedtime_shift_{direction}")
    if consistency_score is not None and consistency_score < _CONSISTENCY_LOW_THRESHOLD:
        extra.append("inconsistent_sleep_timing")

    if not extra:
        return sleep_section

    existing = sleep_section["sleep_duration"]
    updated = existing.model_copy(update={"flags": existing.flags + extra})
    return {**sleep_section, "sleep_duration": updated}


# ── Public API ────────────────────────────────────────────────────────────────


def build_comparison_object(
    records: list[CanonicalDailyRecord],
    analysis_date: date,
) -> ComparisonObject:
    """Build the ComparisonObject for *analysis_date* from the record history.

    Records need not be pre-sorted. The current day is identified by date;
    all prior calendar days feed the baseline windows.
    """
    baseline_set = compute_baselines(records, analysis_date)
    derived = compute_features(records, analysis_date)

    sleep_section = _build_section(_SLEEP_METRICS, baseline_set.metrics)
    heart_health_section = _build_section(_HEART_HEALTH_METRICS, baseline_set.metrics)
    activity_section = _build_section(_ACTIVITY_METRICS, baseline_set.metrics)

    # Enrich sleep section with derived-feature flags
    sleep_section = _enrich_sleep_flags(
        sleep_section,
        derived.bedtime_shift_minutes,
        derived.sleep_consistency_score,
    )

    # Data quality from the current day's record
    current = next(
        (r for r in records if r.date == analysis_date), None
    )
    missing: list[str] = list(current.missing_fields) if current else []
    invalid: list[str] = list(current.invalid_fields) if current else []
    low_conf = any(mb.low_confidence for mb in baseline_set.metrics.values())

    # Build the object (empty associations first — compute_associations needs it)
    comparison = ComparisonObject(
        user_id=baseline_set.user_id,
        analysis_date=analysis_date,
        sleep=sleep_section,
        heart_health=heart_health_section,
        activity=activity_section,
        candidate_associations=[],
        data_quality=DataQuality(
            missing_fields=missing,
            invalid_fields=invalid,
            low_confidence=low_conf,
        ),
    )

    # Compute associations and return the final object
    associations = compute_associations(comparison)
    return comparison.model_copy(update={"candidate_associations": associations})
