"""Normalize raw wearable dict/row into a CanonicalDailyRecord.

Validation rules (FR-003, FR-004):
- Absent / None values: recorded in missing_fields, stored as null.
- Out-of-range values: quarantined into invalid_fields, stored as null.
- Sleep stages summing above total sleep: both stages quarantined.
- Never raises on bad metric data — records and continues.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from .models import CanonicalDailyRecord, UserProfile


# ── Range constraints (inclusive) ────────────────────────────────────────────

_METRIC_RANGES: dict[str, tuple[float, float]] = {
    "sleep_duration_minutes": (0, 1440),
    "sleep_score": (0, 100),
    "deep_sleep_minutes": (0, 600),
    "rem_sleep_minutes": (0, 600),
    "resting_hr": (25, 120),
    "hrv_rmssd_ms": (1.0, 250.0),
    "stress_score": (0, 100),
    "steps": (0, 100_000),
    "active_minutes": (0, 1440),
}

_INT_FIELDS: frozenset[str] = frozenset(
    {
        "sleep_duration_minutes",
        "sleep_score",
        "deep_sleep_minutes",
        "rem_sleep_minutes",
        "resting_hr",
        "stress_score",
        "steps",
        "active_minutes",
    }
)

_BEDTIME_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")

_METRIC_ORDER: tuple[str, ...] = (
    "sleep_duration_minutes",
    "sleep_score",
    "deep_sleep_minutes",
    "rem_sleep_minutes",
    "bedtime",
    "resting_hr",
    "hrv_rmssd_ms",
    "stress_score",
    "steps",
    "active_minutes",
)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _coerce_numeric(field: str, raw_val: Any) -> tuple[Any, bool]:
    """Return (coerced_value, is_valid). Coerces to int or float per field type."""
    try:
        if field in _INT_FIELDS:
            return int(round(float(raw_val))), True
        return float(raw_val), True
    except (TypeError, ValueError):
        return None, False


def _in_range(field: str, val: float) -> bool:
    lo, hi = _METRIC_RANGES[field]
    return lo <= val <= hi


def _sorted_by_order(fields: set[str]) -> list[str]:
    return [f for f in _METRIC_ORDER if f in fields]


# ── Public API ────────────────────────────────────────────────────────────────


def normalize_record(raw: dict[str, Any]) -> CanonicalDailyRecord:
    """Map one raw dict row → CanonicalDailyRecord.

    Always returns a valid model; validation errors are captured in
    missing_fields / invalid_fields rather than raised.
    """
    user_id = str(raw.get("user_id") or "")
    date_raw = raw.get("date")
    try:
        record_date = date.fromisoformat(str(date_raw))
    except (TypeError, ValueError):
        record_date = date.today()

    missing: set[str] = set()
    invalid: set[str] = set()
    values: dict[str, Any] = {}

    # ── Validate numeric metric fields ────────────────────────────────────────
    for field in _METRIC_RANGES:
        raw_val = raw.get(field)
        if raw_val is None:
            values[field] = None
            missing.add(field)
            continue

        coerced, ok = _coerce_numeric(field, raw_val)
        if not ok:
            values[field] = None
            invalid.add(field)
            continue

        if not _in_range(field, coerced):
            values[field] = None
            invalid.add(field)
        else:
            values[field] = coerced

    # ── Validate bedtime ──────────────────────────────────────────────────────
    raw_bedtime = raw.get("bedtime")
    if raw_bedtime is None:
        values["bedtime"] = None
        missing.add("bedtime")
    elif not isinstance(raw_bedtime, str) or not _BEDTIME_RE.match(raw_bedtime):
        values["bedtime"] = None
        invalid.add("bedtime")
    else:
        values["bedtime"] = raw_bedtime

    # ── Sleep stage sum constraint ────────────────────────────────────────────
    duration = values.get("sleep_duration_minutes")
    deep = values.get("deep_sleep_minutes")
    rem = values.get("rem_sleep_minutes")
    if duration is not None and deep is not None and rem is not None:
        if deep + rem > duration:
            for stage in ("deep_sleep_minutes", "rem_sleep_minutes"):
                values[stage] = None
                missing.discard(stage)
                invalid.add(stage)

    return CanonicalDailyRecord(
        user_id=user_id,
        date=record_date,
        **values,
        missing_fields=_sorted_by_order(missing),
        invalid_fields=_sorted_by_order(invalid),
    )


def normalize_records(raws: list[dict[str, Any]]) -> list[CanonicalDailyRecord]:
    """Normalize a sequence of raw rows, preserving order."""
    return [normalize_record(r) for r in raws]


def normalize_profile(raw_profile: dict[str, Any]) -> UserProfile:
    """Normalize a raw profile dict (user_id, records, optional age/gender)."""
    records = normalize_records(raw_profile.get("records", []))
    records_sorted = sorted(records, key=lambda r: r.date)
    return UserProfile(
        user_id=str(raw_profile.get("user_id") or ""),
        age=raw_profile.get("age"),
        gender=raw_profile.get("gender"),
        records=records_sorted,
    )
