"""Deterministic synthetic wearable data generation.

The generator produces wearable-like daily summaries for the phase-1 PoC:

- four lifestyle profiles over a configurable history window
- an explicit recovery-deficit snapshot for the MVP demo
- short, sparse missing-data fragments that mimic occasional sensor gaps

All randomness is seeded and isolated to ``random.Random`` so the same seed and
arguments always yield the same dataset.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import math
import random
from typing import Any, Iterable

DEFAULT_ANALYSIS_DATE = date(2026, 6, 17)
DEFAULT_HISTORY_DAYS = 90
PROFILE_NAMES = (
    "healthy_consistent",
    "poor_sleep_week",
    "low_activity",
    "recovery_decline",
)

_METRIC_ORDER = (
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

_MISSING_GROUPS = {
    "sleep": (
        "sleep_duration_minutes",
        "sleep_score",
        "deep_sleep_minutes",
        "rem_sleep_minutes",
        "bedtime",
    ),
    "recovery": ("resting_hr", "hrv_rmssd_ms", "stress_score"),
    "activity": ("steps", "active_minutes"),
}


@dataclass(frozen=True)
class _ProfileSpec:
    name: str
    user_id: str
    age: int | None
    gender: str | None
    display_name: str
    dob: str  # ISO YYYY-MM-DD (fictional demo persona)
    avatar: str  # avatar filename under ui assets/avatars/
    recovery_base: float
    recovery_drift: float
    stress_base: float
    stress_drift: float
    activity_base: float
    activity_drift: float
    sleep_base: float
    sleep_drift: float
    bedtime_base_minutes: float
    bedtime_drift: float
    noise_scale: float
    missing_probabilities: dict[str, float]


_PROFILE_SPECS = {
    "healthy_consistent": _ProfileSpec(
        name="healthy_consistent",
        user_id="usr_healthy_consistent",
        age=34,
        gender="Non-specified",
        display_name="Aanya Sharma",
        dob="1992-04-12",
        avatar="avatar_healthy.svg",
        recovery_base=0.82,
        recovery_drift=0.0,
        stress_base=0.18,
        stress_drift=0.0,
        activity_base=0.62,
        activity_drift=0.0,
        sleep_base=0.78,
        sleep_drift=0.0,
        bedtime_base_minutes=22 * 60 + 20,
        bedtime_drift=0.0,
        noise_scale=1.0,
        missing_probabilities={"sleep": 0.06, "recovery": 0.04, "activity": 0.03},
    ),
    "poor_sleep_week": _ProfileSpec(
        name="poor_sleep_week",
        user_id="usr_poor_sleep_week",
        age=31,
        gender="Female",
        display_name="Meera Iyer",
        dob="1994-11-20",
        avatar="avatar_poor_sleep.svg",
        recovery_base=0.70,
        recovery_drift=-0.08,
        stress_base=0.28,
        stress_drift=0.10,
        activity_base=0.55,
        activity_drift=-0.05,
        sleep_base=0.72,
        sleep_drift=-0.10,
        bedtime_base_minutes=22 * 60 + 50,
        bedtime_drift=12.0,
        noise_scale=1.15,
        missing_probabilities={"sleep": 0.08, "recovery": 0.05, "activity": 0.04},
    ),
    "low_activity": _ProfileSpec(
        name="low_activity",
        user_id="usr_low_activity",
        age=39,
        gender="Male",
        display_name="Rohan Verma",
        dob="1987-01-22",
        avatar="avatar_low_activity.svg",
        recovery_base=0.66,
        recovery_drift=-0.02,
        stress_base=0.24,
        stress_drift=0.04,
        activity_base=0.20,
        activity_drift=-0.03,
        sleep_base=0.66,
        sleep_drift=-0.03,
        bedtime_base_minutes=23 * 60 + 5,
        bedtime_drift=8.0,
        noise_scale=1.2,
        missing_probabilities={"sleep": 0.05, "recovery": 0.04, "activity": 0.07},
    ),
    "recovery_decline": _ProfileSpec(
        name="recovery_decline",
        user_id="usr_recovery_decline",
        age=36,
        gender="Non-specified",
        display_name="Kabir Nair",
        dob="1989-07-18",
        avatar="avatar_recovery_decline.svg",
        recovery_base=0.80,
        recovery_drift=-0.48,
        stress_base=0.20,
        stress_drift=0.42,
        activity_base=0.50,
        activity_drift=-0.10,
        sleep_base=0.74,
        sleep_drift=-0.06,
        bedtime_base_minutes=22 * 60 + 35,
        bedtime_drift=18.0,
        noise_scale=1.1,
        missing_probabilities={"sleep": 0.05, "recovery": 0.08, "activity": 0.04},
    ),
}


def _as_date(value: date | str | None) -> date:
    if value is None:
        return DEFAULT_ANALYSIS_DATE
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _maybe_int(value: float) -> int:
    return int(round(value))


def _hhmm_from_minutes(minutes: float) -> str:
    rounded = int(round(minutes)) % (24 * 60)
    return f"{rounded // 60:02d}:{rounded % 60:02d}"


def _week_sine(day_index: int, phase: float = 0.0) -> float:
    return math.sin((2.0 * math.pi * day_index / 7.0) + phase)


def _month_sine(day_index: int, phase: float = 0.0) -> float:
    return math.sin((2.0 * math.pi * day_index / 30.0) + phase)


def _weighted_noise(rng: random.Random, scale: float) -> float:
    return rng.gauss(0.0, scale)


def _jitter_spec(spec: _ProfileSpec, *, seed: int, jitter: float) -> _ProfileSpec:
    """Return a copy of *spec* with base parameters slightly perturbed.

    Uses an RNG isolated from the main data-generation RNG so that enabling
    jitter does not shift every downstream random draw.  The same (seed, jitter)
    pair always produces the same perturbed spec, keeping results reproducible.
    """
    if jitter <= 0.0:
        return spec

    rng = random.Random(seed ^ 0xDEAD_BEEF)

    def _jg(center: float, scale: float) -> float:
        return center + rng.gauss(0.0, scale * jitter)

    return _ProfileSpec(
        name=spec.name,
        user_id=spec.user_id,
        age=spec.age,
        gender=spec.gender,
        display_name=spec.display_name,
        dob=spec.dob,
        avatar=spec.avatar,
        recovery_base=_clamp(_jg(spec.recovery_base, 0.06), 0.0, 1.0),
        recovery_drift=_jg(spec.recovery_drift, 0.03),
        stress_base=_clamp(_jg(spec.stress_base, 0.06), 0.0, 1.0),
        stress_drift=_jg(spec.stress_drift, 0.03),
        activity_base=_clamp(_jg(spec.activity_base, 0.06), 0.0, 1.0),
        activity_drift=_jg(spec.activity_drift, 0.03),
        sleep_base=_clamp(_jg(spec.sleep_base, 0.06), 0.0, 1.0),
        sleep_drift=_jg(spec.sleep_drift, 0.03),
        bedtime_base_minutes=_clamp(_jg(spec.bedtime_base_minutes, 18.0), 20 * 60, 26 * 60),
        bedtime_drift=_jg(spec.bedtime_drift, 3.0),
        noise_scale=_clamp(_jg(spec.noise_scale, 0.12), 0.5, 2.0),
        missing_probabilities=spec.missing_probabilities,
    )


def _profile_spec(profile: str) -> _ProfileSpec:
    if profile == "recovery_deficit":
        return _ProfileSpec(
            name="recovery_deficit",
            user_id="usr_recovery_deficit",
            age=33,
            gender="Non-specified",
            display_name="Saurabh Gupta",
            dob="1992-12-27",
            avatar="avatar_recovery_deficit.svg",
            recovery_base=0.82,
            recovery_drift=0.0,
            stress_base=0.18,
            stress_drift=0.0,
            activity_base=0.60,
            activity_drift=0.0,
            sleep_base=0.78,
            sleep_drift=0.0,
            bedtime_base_minutes=22 * 60 + 25,
            bedtime_drift=0.0,
            noise_scale=0.8,
            missing_probabilities={"sleep": 0.0, "recovery": 0.0, "activity": 0.0},
        )
    try:
        return _PROFILE_SPECS[profile]
    except KeyError as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"Unknown profile '{profile}'") from exc


def _latent_state(
    spec: _ProfileSpec,
    *,
    day_index: int,
    total_days: int,
    rng: random.Random,
) -> dict[str, float]:
    progress = day_index / max(total_days - 1, 1)
    weekly = _week_sine(day_index, phase=0.45)
    monthly = _month_sine(day_index, phase=1.15)

    recovery = spec.recovery_base + (spec.recovery_drift * progress)
    stress = spec.stress_base + (spec.stress_drift * progress)
    activity = spec.activity_base + (spec.activity_drift * progress)
    sleep = spec.sleep_base + (spec.sleep_drift * progress)
    bedtime = spec.bedtime_base_minutes + (spec.bedtime_drift * progress)

    if spec.name == "healthy_consistent":
        recovery += 0.02 * weekly + 0.02 * monthly
        stress += -0.01 * weekly + 0.01 * monthly
        activity += 0.05 * weekly
        sleep += 0.01 * monthly
        bedtime += 4.0 * weekly
    elif spec.name == "poor_sleep_week":
        bad_week_start = max(0, int(total_days * 0.62))
        bad_week_end = min(total_days, bad_week_start + 7)
        if bad_week_start <= day_index < bad_week_end:
            recovery -= 0.28
            stress += 0.42
            activity -= 0.18
            sleep -= 0.26
            bedtime += 32.0
        recovery += 0.01 * weekly
        stress += 0.04 * monthly
        activity -= 0.02 * weekly
        sleep -= 0.03 * monthly
        bedtime += 8.0 * monthly
    elif spec.name == "low_activity":
        recovery += 0.01 * weekly
        stress += 0.01 * monthly
        activity += -0.08 * weekly
        sleep += -0.02 * monthly
        bedtime += 18.0 * weekly
    elif spec.name == "recovery_decline":
        recovery += -0.08 * progress + 0.02 * weekly
        stress += 0.10 * progress + 0.02 * monthly
        activity += -0.03 * progress + 0.03 * weekly
        sleep += -0.02 * progress
        bedtime += 18.0 * progress + 6.0 * weekly
    elif spec.name == "recovery_deficit":
        if day_index < total_days - 1:
            recovery = 0.82 + 0.02 * weekly + 0.01 * monthly
            stress = 0.18 + 0.01 * monthly
            activity = 0.60 + 0.04 * weekly
            sleep = 0.78 + 0.01 * monthly
            bedtime = 22 * 60 + 25 + 5.0 * weekly
        else:
            recovery = 0.10
            stress = 0.90
            activity = 0.04
            sleep = 0.16
            bedtime = 24 * 60 + 5

    recovery += _weighted_noise(rng, 0.02 * spec.noise_scale)
    stress += _weighted_noise(rng, 0.03 * spec.noise_scale)
    activity += _weighted_noise(rng, 0.03 * spec.noise_scale)
    sleep += _weighted_noise(rng, 0.03 * spec.noise_scale)
    bedtime += _weighted_noise(rng, 8.0 * spec.noise_scale)

    return {
        "recovery": _clamp(recovery, 0.0, 1.0),
        "stress": _clamp(stress, 0.0, 1.0),
        "activity": _clamp(activity, 0.0, 1.0),
        "sleep": _clamp(sleep, 0.0, 1.0),
        "bedtime_minutes": _clamp(bedtime, 20 * 60, 27 * 60),
    }


def _metrics_from_latent(state: dict[str, float], rng: random.Random, noise_scale: float) -> dict[str, Any]:
    recovery = state["recovery"]
    stress = state["stress"]
    activity = state["activity"]
    sleep = state["sleep"]
    bedtime_minutes = state["bedtime_minutes"]

    sleep_duration = 360 + 180 * sleep + 30 * recovery - 60 * stress + _weighted_noise(rng, 16.0 * noise_scale)
    sleep_duration = _clamp(sleep_duration, 0, 1440)

    sleep_score = 44 + 40 * sleep + 18 * recovery - 24 * stress + _weighted_noise(rng, 4.0 * noise_scale)
    sleep_score = _clamp(sleep_score, 0, 100)

    deep_sleep = 0.18 * sleep_duration + 18 * recovery - 8 * stress + _weighted_noise(rng, 5.0 * noise_scale)
    rem_sleep = 0.16 * sleep_duration + 10 * recovery - 6 * stress + _weighted_noise(rng, 4.0 * noise_scale)

    if deep_sleep + rem_sleep > sleep_duration:
        scale = sleep_duration / max(deep_sleep + rem_sleep, 1.0)
        deep_sleep *= scale * 0.92
        rem_sleep *= scale * 0.86

    deep_sleep = _clamp(deep_sleep, 0, min(600, sleep_duration))
    rem_sleep = _clamp(rem_sleep, 0, min(600, sleep_duration - deep_sleep))

    resting_hr = 66 - 10 * recovery + 8 * stress - 4 * activity + _weighted_noise(rng, 1.8 * noise_scale)
    resting_hr = _clamp(resting_hr, 25, 120)

    hrv = 96 + 28 * recovery - 26 * stress + 8 * activity + _weighted_noise(rng, 3.6 * noise_scale)
    hrv = _clamp(hrv, 1, 250)

    stress_score = 100 * (0.42 * stress + 0.16 * (1 - recovery) + 0.08 * (1 - activity))
    stress_score += _weighted_noise(rng, 3.0 * noise_scale)
    stress_score = _clamp(stress_score, 0, 100)

    steps = 12800 * activity - 2400 * stress + 600 * recovery + _weighted_noise(rng, 650.0 * noise_scale)
    steps = _clamp(steps, 0, 100000)

    active_minutes = 110 * activity - 22 * stress + 12 * recovery + _weighted_noise(rng, 6.0 * noise_scale)
    active_minutes = _clamp(active_minutes, 0, 1440)

    return {
        "sleep_duration_minutes": _maybe_int(sleep_duration),
        "sleep_score": _maybe_int(sleep_score),
        "deep_sleep_minutes": _maybe_int(deep_sleep),
        "rem_sleep_minutes": _maybe_int(rem_sleep),
        "bedtime": _hhmm_from_minutes(bedtime_minutes),
        "resting_hr": _maybe_int(resting_hr),
        "hrv_rmssd_ms": round(hrv, 1),
        "stress_score": _maybe_int(stress_score),
        "steps": _maybe_int(steps),
        "active_minutes": _maybe_int(active_minutes),
    }


def _missing_spans(
    spec: _ProfileSpec,
    *,
    total_days: int,
    rng: random.Random,
) -> list[tuple[str, range]]:
    if spec.name == "recovery_deficit":
        return []

    occupied: set[int] = set()
    spans: list[tuple[str, range]] = []

    for group_name in ("sleep", "recovery", "activity"):
        chance = spec.missing_probabilities.get(group_name, 0.0)
        if rng.random() >= chance:
            continue

        length = 1 if total_days < 12 else rng.randint(1, 2)
        lower_bound = 2
        upper_bound = max(lower_bound, total_days - length - 2)

        candidate_indices = [
            index
            for index in range(lower_bound, upper_bound + 1)
            if not any(position in occupied for position in range(index, index + length))
        ]
        if not candidate_indices:
            continue

        start = candidate_indices[rng.randrange(len(candidate_indices))]
        span = range(start, start + length)
        spans.append((group_name, span))
        occupied.update(span)

    if not spans and total_days >= 6:
        fallback_group = max(spec.missing_probabilities, key=spec.missing_probabilities.get, default="activity")
        if spec.missing_probabilities.get(fallback_group, 0.0) <= 0:
            fallback_group = "activity"

        length = 1
        lower_bound = 2
        upper_bound = max(lower_bound, total_days - length - 2)
        candidate_indices = [
            index
            for index in range(lower_bound, upper_bound + 1)
            if not any(position in occupied for position in range(index, index + length))
        ]
        if candidate_indices:
            start = candidate_indices[len(candidate_indices) // 2]
            span = range(start, start + length)
            spans.append((fallback_group, span))

    return spans


def _apply_missing_fragments(records: list[dict[str, Any]], spec: _ProfileSpec, rng: random.Random) -> None:
    spans = _missing_spans(spec, total_days=len(records), rng=rng)
    if not spans:
        return

    for group_name, span in spans:
        fields = _MISSING_GROUPS[group_name]
        for day_index in span:
            record = records[day_index]
            for field in fields:
                record[field] = None
            missing = set(record["missing_fields"])
            missing.update(fields)
            record["missing_fields"] = [field for field in _METRIC_ORDER if field in missing]


def _build_records(
    spec: _ProfileSpec,
    *,
    days: int,
    end_date: date,
    seed: int,
) -> list[dict[str, Any]]:
    if days < 1:
        raise ValueError("days must be at least 1")

    rng = random.Random(seed)
    start_date = end_date - timedelta(days=days - 1)
    records: list[dict[str, Any]] = []

    for offset in range(days):
        current_date = start_date + timedelta(days=offset)
        latent = _latent_state(spec, day_index=offset, total_days=days, rng=rng)
        metrics = _metrics_from_latent(latent, rng=rng, noise_scale=spec.noise_scale)
        record = {
            "user_id": spec.user_id,
            "date": current_date.isoformat(),
            **metrics,
            "missing_fields": [],
            "invalid_fields": [],
        }
        records.append(record)

    _apply_missing_fragments(records, spec, rng)
    return records


def _profile_dict(
    profile: str,
    *,
    seed: int,
    days: int,
    end_date: date | str | None,
    user_id: str | None,
    jitter: float = 0.0,
) -> dict[str, Any]:
    spec = _jitter_spec(_profile_spec(profile), seed=seed, jitter=jitter)
    resolved_end_date = _as_date(end_date)
    records = _build_records(spec, days=days, end_date=resolved_end_date, seed=seed)

    payload: dict[str, Any] = {
        "user_id": user_id or spec.user_id,
        "records": records,
        "display_name": spec.display_name,
        "dob": spec.dob,
        "avatar": spec.avatar,
    }
    if spec.age is not None:
        payload["age"] = spec.age
    if spec.gender is not None:
        payload["gender"] = spec.gender
    return payload


def generate_synthetic_profile(
    profile: str,
    *,
    seed: int = 42,
    days: int = DEFAULT_HISTORY_DAYS,
    end_date: date | str | None = None,
    user_id: str | None = None,
    jitter: float = 0.0,
) -> dict[str, Any]:
    """Generate one synthetic profile with time-ordered daily records.

    Args:
        profile: One of the named profiles (e.g. ``"healthy_consistent"``).
        seed: RNG seed — same seed + same jitter always produces identical output.
        days: Number of calendar days to generate.
        end_date: Last date in the series; defaults to :data:`DEFAULT_ANALYSIS_DATE`.
        user_id: Override the default user ID embedded in the profile spec.
        jitter: Scale of random perturbation applied to the profile's base
            parameters before data generation.  ``0.0`` (default) is fully
            deterministic and reproduces the canonical profile exactly.
            ``0.5`` introduces moderate variation (different baselines, slightly
            shifted drift magnitudes) that feels like a distinct person sharing
            the same lifestyle pattern.  ``1.0`` applies the maximum built-in
            perturbation.  Values are reproducible — (seed, jitter) uniquely
            determine the perturbed spec.
    """

    return _profile_dict(profile, seed=seed, days=days, end_date=end_date, user_id=user_id, jitter=jitter)


def generate_wearable_profile(
    profile: str,
    *,
    seed: int = 42,
    days: int = DEFAULT_HISTORY_DAYS,
    end_date: date | str | None = None,
    user_id: str | None = None,
    jitter: float = 0.0,
) -> dict[str, Any]:
    """Alias for :func:`generate_synthetic_profile`."""

    return generate_synthetic_profile(
        profile,
        seed=seed,
        days=days,
        end_date=end_date,
        user_id=user_id,
        jitter=jitter,
    )


def generate_synthetic_dataset(
    *,
    seed: int = 42,
    days: int = DEFAULT_HISTORY_DAYS,
    end_date: date | str | None = None,
    profiles: Iterable[str] | None = None,
    jitter: float = 0.0,
) -> list[dict[str, Any]]:
    """Generate multiple synthetic profiles as a list of user-profile payloads."""

    profile_names = tuple(profiles) if profiles is not None else PROFILE_NAMES
    return [
        generate_synthetic_profile(profile_name, seed=seed + index, days=days, end_date=end_date, jitter=jitter)
        for index, profile_name in enumerate(profile_names)
    ]


def generate_wearable_dataset(
    *,
    seed: int = 42,
    days: int = DEFAULT_HISTORY_DAYS,
    end_date: date | str | None = None,
    profiles: Iterable[str] | None = None,
    jitter: float = 0.0,
) -> list[dict[str, Any]]:
    """Alias for :func:`generate_synthetic_dataset`."""

    return generate_synthetic_dataset(seed=seed, days=days, end_date=end_date, profiles=profiles, jitter=jitter)


def generate_multi_profile_dataset(
    *,
    seed: int = 42,
    days: int = DEFAULT_HISTORY_DAYS,
    end_date: date | str | None = None,
    jitter: float = 0.0,
) -> list[dict[str, Any]]:
    """Generate the four canonical lifestyle profiles in a fixed order."""

    return generate_synthetic_dataset(seed=seed, days=days, end_date=end_date, jitter=jitter)


def generate_multi_profile_index(
    *,
    seed: int = 42,
    days: int = DEFAULT_HISTORY_DAYS,
    end_date: date | str | None = None,
    jitter: float = 0.0,
) -> dict[str, dict[str, Any]]:
    """Generate the canonical profiles keyed by profile name."""

    return {
        profile_name: generate_synthetic_profile(
            profile_name,
            seed=seed + index,
            days=days,
            end_date=end_date,
            jitter=jitter,
        )
        for index, profile_name in enumerate(PROFILE_NAMES)
    }


def build_recovery_deficit_snapshot(
    *,
    seed: int = 42,
    days: int = 31,
    end_date: date | str | None = None,
    jitter: float = 0.0,
) -> dict[str, Any]:
    """Build the high-stress / sedentary recovery-deficit demo case.

    The default 31-day window gives the final day plus a 30-day historical context.
    """

    return generate_synthetic_profile(
        "recovery_deficit",
        seed=seed,
        days=days,
        end_date=end_date,
        jitter=jitter,
    )


generate_recovery_deficit_snapshot = build_recovery_deficit_snapshot


def generate_today_record(
    profile: str,
    *,
    seed: int = 42,
    analysis_date: date | str | None = None,
    total_days: int = DEFAULT_HISTORY_DAYS,
) -> dict[str, Any]:
    """Generate just the 'today' record with an independent seed.

    Uses the same latent-state logic as the full pipeline (today is always
    ``day_index = total_days - 1``), but starts from a fresh RNG so callers
    can re-roll today's noise without touching historical records.
    """
    spec = _profile_spec(profile)
    resolved_date = _as_date(analysis_date)
    rng = random.Random(seed)
    day_index = total_days - 1
    latent = _latent_state(spec, day_index=day_index, total_days=total_days, rng=rng)
    metrics = _metrics_from_latent(latent, rng=rng, noise_scale=spec.noise_scale)
    return {
        "user_id": spec.user_id,
        "date": resolved_date.isoformat(),
        **metrics,
        "missing_fields": [],
        "invalid_fields": [],
    }


# ── Public persona catalog (ClaimGuard integration) ───────────────────────────
# ``PROFILE_NAMES`` deliberately excludes ``recovery_deficit``, which ``_profile_spec``
# synthesizes on demand as the MVP demo persona.  API callers need the full set, so it
# is enumerated separately here rather than by widening PROFILE_NAMES (which would
# change ``generate_multi_profile_dataset`` output and break golden tests).

PERSONA_NAMES: tuple[str, ...] = ("recovery_deficit", *PROFILE_NAMES)


def list_persona_specs() -> list[dict[str, Any]]:
    """Return public, serializable metadata for every selectable persona.

    Exposes only presentation fields — the latent-state generator parameters
    (``recovery_base``, drift terms, noise scale, missing probabilities) stay private
    so the API contract cannot leak the data-generation model.
    """
    specs: list[dict[str, Any]] = []
    for name in PERSONA_NAMES:
        spec = _profile_spec(name)
        specs.append(
            {
                "persona": name,
                "engine_user_id": spec.user_id,
                "display_name": spec.display_name,
                "dob": spec.dob,
                "age": spec.age,
                "gender": spec.gender,
                "avatar": spec.avatar,
            }
        )
    return specs
