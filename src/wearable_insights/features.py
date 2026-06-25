"""Derived wearable features computed from a record history (FR-006).

Three derived features are produced per analysis day:

- sleep_stage_ratio      (deep + rem) / total_duration for the current day.
- bedtime_shift_minutes  Current bedtime minus the 7-day prior mean bedtime.
- sleep_consistency_score  1.0 = perfectly stable bedtime, 0.0 = 60+ min of
                           nightly variation, clamped to [0, 1].

All values are null when required input data is missing.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date

from .models import CanonicalDailyRecord


# ── Bedtime helpers ───────────────────────────────────────────────────────────

# Bedtimes before 06:00 are treated as the following calendar day so that
# 23:50 → 00:10 shifts measure correctly as ~20 min rather than ~1420 min.
_EARLY_MORNING_CUTOFF_H = 6


def _bedtime_to_minutes(bedtime: str | None) -> float | None:
    """Convert 'HH:MM' to minutes-since-noon-prior-day (monotone across midnight)."""
    if bedtime is None:
        return None
    try:
        h, m = map(int, bedtime.split(":"))
    except (ValueError, AttributeError):
        return None
    minutes = h * 60 + m
    if h < _EARLY_MORNING_CUTOFF_H:
        minutes += 24 * 60
    return float(minutes)


# ── Feature container ─────────────────────────────────────────────────────────


@dataclass
class DerivedFeatures:
    """Derived features for one analysis date."""

    sleep_stage_ratio: float | None = None
    """(deep_sleep + rem_sleep) / sleep_duration; null when any input is null."""

    bedtime_shift_minutes: float | None = None
    """Current bedtime minus 7-day prior mean; positive = later than usual."""

    sleep_consistency_score: float | None = None
    """Stability of bedtime over the surrounding window; range [0.0, 1.0]."""


# ── Public API ────────────────────────────────────────────────────────────────

_CONSISTENCY_STD_MAX = 60.0  # std_dev (min) that maps to a score of 0.0
_CONSISTENCY_MIN_POINTS = 3   # need at least this many bedtime values to score


def compute_features(
    records: list[CanonicalDailyRecord],
    analysis_date: date,
) -> DerivedFeatures:
    """Compute derived features for *analysis_date* given the full record history.

    Records need not be pre-sorted; only the current day and the 7 immediately
    prior days are used.
    """
    sorted_records = sorted(records, key=lambda r: r.date)
    current = next((r for r in sorted_records if r.date == analysis_date), None)

    # ── Sleep stage ratio (current day only) ──────────────────────────────────
    stage_ratio: float | None = None
    if current is not None:
        dur = current.sleep_duration_minutes
        deep = current.deep_sleep_minutes
        rem = current.rem_sleep_minutes
        if dur is not None and dur > 0 and deep is not None and rem is not None:
            stage_ratio = round((deep + rem) / dur, 3)

    # ── Prior records (excluding the current day) ─────────────────────────────
    prior_7 = [r for r in sorted_records if r.date < analysis_date][-7:]

    # ── Bedtime shift: current vs 7-day prior mean ────────────────────────────
    bedtime_shift: float | None = None
    current_bt = _bedtime_to_minutes(current.bedtime if current else None)
    prior_bts = [
        _bedtime_to_minutes(r.bedtime)
        for r in prior_7
        if r.bedtime is not None
    ]
    prior_bts_valid = [v for v in prior_bts if v is not None]

    if current_bt is not None and prior_bts_valid:
        bedtime_shift = round(current_bt - statistics.mean(prior_bts_valid), 1)

    # ── Sleep consistency: std-dev of all available bedtimes in the window ────
    consistency: float | None = None
    all_bts = prior_bts_valid + ([current_bt] if current_bt is not None else [])
    if len(all_bts) >= _CONSISTENCY_MIN_POINTS:
        std_dev = statistics.stdev(all_bts)
        consistency = round(max(0.0, 1.0 - std_dev / _CONSISTENCY_STD_MAX), 2)

    return DerivedFeatures(
        sleep_stage_ratio=stage_ratio,
        bedtime_shift_minutes=bedtime_shift,
        sleep_consistency_score=consistency,
    )
