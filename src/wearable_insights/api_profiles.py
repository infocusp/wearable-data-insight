"""Memoized reconstruction of profiles and slotted baselines.

Both underlying builders are pure functions, so these caches are purely *derived*:
losing them costs latency, never correctness.  That is what lets the service scale
horizontally and restart freely.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Any

from .api_models import ProfileRef
from .data.slotted_baselines import SlottedBaselineSet, build_slotted_baselines
from .data.synthetic import generate_synthetic_profile, list_persona_specs
from .config import BASELINE_HISTORY_DAYS, BASELINE_SEED

_PERSONA_INDEX: dict[str, dict[str, Any]] = {
    spec["persona"]: spec for spec in list_persona_specs()
}


def persona_meta(persona: str) -> dict[str, Any]:
    """Public presentation metadata for one persona."""
    return _PERSONA_INDEX[persona]


@lru_cache(maxsize=128)
def _profile_cached(
    persona: str, seed: int, days: int, end_date_iso: str, jitter: float, user_id: str | None
) -> dict[str, Any]:
    return generate_synthetic_profile(
        persona,
        seed=seed,
        days=days,
        end_date=date.fromisoformat(end_date_iso),
        user_id=user_id,
        jitter=jitter,
    )


def build_profile(ref: ProfileRef) -> dict[str, Any]:
    """Reconstruct the profile dict for *ref* (cached).

    Returns a deep-ish copy guard: callers must not mutate the cached dict, so the
    records list is re-wrapped.  The record dicts themselves are treated as read-only
    by every consumer in the engine.
    """
    cached = _profile_cached(
        ref.persona, ref.seed, ref.days, ref.end_date.isoformat(), ref.jitter, ref.user_id
    )
    return {**cached, "records": list(cached["records"])}


@lru_cache(maxsize=256)
def _slotted_cached(
    resting_hr: float,
    hrv: float,
    ref_date_iso: str,
    seed: int,
    history_days: int,
) -> SlottedBaselineSet:
    # Keyed on ONLY the two record fields live_baselines() actually reads, rounded, so
    # many personas/dates collapse onto a handful of entries.
    return build_slotted_baselines(
        {"resting_hr": resting_hr, "hrv_rmssd_ms": hrv},
        seed=seed,
        history_days=history_days,
        ref_date=date.fromisoformat(ref_date_iso),
    )


def build_baselines(
    record: dict[str, Any] | None,
    ref_date: date,
    *,
    seed: int = BASELINE_SEED,
    history_days: int = BASELINE_HISTORY_DAYS,
) -> SlottedBaselineSet:
    """Slotted baselines for *record* anchored at *ref_date* (cached).

    ``ref_date`` is always passed explicitly — never allowed to default to
    ``date.today()`` inside a request path.
    """
    record = record or {}
    resting = round(float(record.get("resting_hr") or 60), 0)
    hrv = round(float(record.get("hrv_rmssd_ms") or 55.0), 1)
    return _slotted_cached(resting, hrv, ref_date.isoformat(), seed, history_days)


def warm_baselines(end_date: date) -> int:
    """Pre-build caches for every persona at *end_date*; returns how many were warmed."""
    warmed = 0
    for persona in _PERSONA_INDEX:
        ref = ProfileRef(persona=persona, end_date=end_date)  # type: ignore[arg-type]
        profile = build_profile(ref)
        records = profile.get("records") or []
        if records:
            build_baselines(records[-1], end_date)
            warmed += 1
    return warmed


def cache_stats() -> dict[str, Any]:
    return {
        "profiles": _profile_cached.cache_info()._asdict(),
        "baselines": _slotted_cached.cache_info()._asdict(),
    }
