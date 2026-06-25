"""Slotted time-of-day baselines for live-anomaly detection (Feature 004).

The 24-hour day is divided into 8 fixed 3-hour slots, crossed with a weekday/weekend
split = 16 buckets per signal. Synthetic historical data is generated from the existing
diurnal/mode model in ``data/live.py`` and aggregated into per-(signal, slot, day_type,
horizon_days) bucket averages. All math is deterministic (seed-reproducible) and happens
before the model is invoked (constitution Principle I).

Public API::

    baselines = build_slotted_baselines(record)   # SlottedBaselineSet
    slot      = slot_index(minute)                 # int 0-7
    dt        = day_type(weekday)                  # "weekday" | "weekend"
    anchor    = lookup_anchor(baselines, signal, slot, dt, horizon)  # float | None
    label     = slot_label(slot)                   # "HH:00–HH:00"
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .live import LIVE_SIGNALS, fetch_latest_sample, live_baselines

SLOT_COUNT: int = 8
SLOT_WIDTH_MINUTES: int = 180  # 3 hours

# Internal bucket key: (signal, slot_index, day_type, horizon_days)
_BucketKey = tuple[str, int, str, int]


@dataclass
class SlottedBaselineSet:
    """Per-(signal, slot, day_type, horizon) averages built from synthetic history."""

    averages: dict[_BucketKey, float] = field(default_factory=dict)
    counts: dict[_BucketKey, int] = field(default_factory=dict)
    flat_anchors: dict[str, float] = field(default_factory=dict)
    horizons: tuple[int, ...] = (7, 30)
    min_samples: int = 3


def slot_index(minute: int) -> int:
    """Return the 0-based 3-hour slot index (0–7) for a device minute-of-day."""
    return (minute % 1440) // SLOT_WIDTH_MINUTES


def day_type(weekday: int) -> str:
    """Return 'weekday' or 'weekend' from a Python datetime.weekday() value (0=Mon)."""
    return "weekend" if weekday >= 5 else "weekday"


def slot_label(slot: int) -> str:
    """Human-readable label for a slot, e.g. '09:00–12:00'."""
    start_h = slot * 3
    end_h = (slot + 1) * 3
    return f"{start_h:02d}:00–{end_h:02d}:00"


def _mode_at(minute: int, schedule: list[tuple[int, str]]) -> str:
    """Return the mode active at *minute* given a sorted (start, mode) schedule."""
    mode = "resting"
    for start, m in schedule:
        if minute >= start:
            mode = m
    return mode


def build_slotted_baselines(
    record: dict[str, Any] | None,
    *,
    seed: int = 42,
    history_days: int = 60,
    horizons: tuple[int, ...] = (7, 30),
    min_samples: int = 3,
    sample_step_minutes: int = 5,
    ref_date: date | None = None,
) -> SlottedBaselineSet:
    """Build per-(signal, slot, day_type, horizon) bucket averages from synthetic history.

    Generates ``history_days`` days of intraday samples using ``live.fetch_latest_sample``
    (the existing diurnal/mode model), then aggregates them into buckets. Reproducible:
    same ``seed`` + ``ref_date`` always yields identical bucket averages.

    Args:
        record:            Today's daily record dict (used by ``live_baselines`` for HR/HRV
                           anchors). Pass None to use defaults.
        seed:              Master RNG seed for reproducible generation.
        history_days:      How many days of synthetic history to generate.
        horizons:          Look-back horizons (days) to aggregate over.
        min_samples:       Minimum samples for a bucket to be considered reliable.
        sample_step_minutes: Device sample cadence in minutes.
        ref_date:          Reference "today" (defaults to date.today()).
    """
    flat = live_baselines(record)
    ref = ref_date or date.today()
    signal_keys = [s["key"] for s in LIVE_SIGNALS]

    # (signal, slot, day_type, horizon_days) -> accumulated values
    accum: dict[_BucketKey, list[float]] = {}

    for day_offset in range(history_days):
        sim_date = ref - timedelta(days=history_days - day_offset)
        dt = day_type(sim_date.weekday())
        days_ago = history_days - day_offset  # 1 = yesterday, history_days = oldest

        # Per-day RNG: mixing seed with date ordinal keeps each day independent yet
        # reproducible regardless of the iteration order.
        day_seed = seed ^ (sim_date.toordinal() * 6271)
        day_rng = random.Random(day_seed)

        # Randomised but realistic daily mode schedule (constitution Principle VI).
        active_start = day_rng.randint(360, 480)    # 06:00–08:00
        stressed_start = day_rng.randint(720, 900)  # 12:00–15:00
        schedule: list[tuple[int, str]] = [
            (0, "resting"),
            (active_start, day_rng.choice(["resting", "active"])),
            (stressed_start, day_rng.choice(["resting", "stressed"])),
            (1080, "resting"),  # 18:00 back to resting
        ]

        for minute in range(0, 1440, sample_step_minutes):
            slot = slot_index(minute)
            mode = _mode_at(minute, schedule)
            # Per-sample RNG independent of day_rng so schedule choices don't shift samples.
            sample_rng = random.Random(day_seed ^ (minute * 104729))
            sample = fetch_latest_sample(flat, minute, mode, rng=sample_rng)

            for sig in signal_keys:
                val = sample.get(sig)
                if val is None:
                    continue
                fval = float(val)
                for h in horizons:
                    if days_ago <= h:
                        key: _BucketKey = (sig, slot, dt, h)
                        if key not in accum:
                            accum[key] = []
                        accum[key].append(fval)

    averages: dict[_BucketKey, float] = {}
    counts: dict[_BucketKey, int] = {}
    for key, vals in accum.items():
        counts[key] = len(vals)
        averages[key] = sum(vals) / len(vals)

    return SlottedBaselineSet(
        averages=averages,
        counts=counts,
        flat_anchors=flat,
        horizons=horizons,
        min_samples=min_samples,
    )


def lookup_anchor(
    baselines: SlottedBaselineSet,
    signal: str,
    slot: int,
    dt: str,
    horizon: int,
) -> float | None:
    """Return the bucket average for (signal, slot, dt, horizon), with fallback.

    Fallback chain (FR-006):
      1. Exact bucket if ``count >= min_samples``.
      2. Average of all reliable same-(signal, dt, horizon) buckets across all slots.
      3. Flat resting anchor from ``baselines.flat_anchors``.
      4. None — signal is fully unknown; caller skips it.
    """
    key: _BucketKey = (signal, slot, dt, horizon)
    if baselines.counts.get(key, 0) >= baselines.min_samples:
        return baselines.averages[key]

    # Fallback: average reliable slots for same (signal, dt, horizon).
    fallback_vals = [
        baselines.averages[(signal, s, dt, horizon)]
        for s in range(SLOT_COUNT)
        if baselines.counts.get((signal, s, dt, horizon), 0) >= baselines.min_samples
    ]
    if fallback_vals:
        return sum(fallback_vals) / len(fallback_vals)

    return baselines.flat_anchors.get(signal)
