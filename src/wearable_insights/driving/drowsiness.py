"""Driver-drowsiness assessment (ClaimGuard integration, stage C).

Mocks a wearable that also reports driver-drowsiness, for use as **corroborating context
at motor-claim time**.  The mock is deterministic and derived from real signals already in
the member's profile (sleep debt, last night's sleep, HRV suppression, resting-HR drift,
circadian timing) plus the intraday simulator — not from a random number.

Framing matters as much as the number here, so it is stated in the contract itself:

    A drowsiness signal is evidence about **causation and liability** — was the driver
    impaired by fatigue — and is **not** evidence of fraud.  A high score should deepen
    an investigation into how a collision happened; it must never, on its own, imply the
    claimant is being dishonest.

All arithmetic is deterministic Python; no LLM is involved anywhere in this module.

Calibration note (measured, not assumed)
----------------------------------------
Two of the six contributors (``hrv_drop_pct``, ``resting_hr_delta``) are *relative* to the
member's own baseline, so a chronically impaired driver — someone who always sleeps four
hours — shows no deviation on them and caps around the top of ``moderate`` rather than
reaching ``severe``.  The two absolute sleep contributors do still fire at full weight in
that case, so the signal is a modest under-read, not a blind spot.

``severe`` is reserved for, and reachable by, the genuinely worst combination: an acute
collapse against a healthy baseline, during a circadian trough, after a long unbroken
drive.  That ordering is intentional.

Do **not** "fix" the chronic case by introducing absolute HRV or resting-HR thresholds.
Those are population-level clinical cutoffs; adopting them would turn this module from an
associative signal into a diagnostic one and breach constitution Principle II.
"""

from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..data.live import fetch_latest_sample, live_baselines
from ..models import CanonicalDailyRecord, UserProfile
from ..normalize import normalize_profile

Level = Literal["alert", "mild", "moderate", "severe"]

# Score bands. `moderate` is the threshold at which an episode is worth an adjuster's
# attention and at which a deterministic flag is raised.
_LEVEL_BANDS: tuple[tuple[int, Level], ...] = ((75, "severe"), (50, "moderate"), (25, "mild"))
MODERATE_THRESHOLD = 50

_TARGET_SLEEP_MINUTES = 420  # 7 hours; the reference point for "sleep debt"
_SAMPLE_STEP_MINUTES = 5

# Contributor weights. Sleep quantity dominates because it is the best-evidenced
# predictor of fatigue impairment; drive duration and circadian timing modulate it.
_WEIGHTS: dict[str, float] = {
    "prior_sleep_debt_min": 0.24,
    "sleep_duration_last_night": 0.22,
    "hrv_drop_pct": 0.18,
    "resting_hr_delta": 0.08,
    "time_of_day_circadian_risk": 0.16,
    "continuous_drive_minutes": 0.12,
}

DROWSINESS_DISCLAIMER: str = (
    "Derived from voluntarily shared wearable data as corroborating context for how an "
    "incident occurred. It indicates fatigue risk, not fraud, and is not a medical "
    "assessment. It must be reviewed by a human adjuster alongside other evidence."
)


class Contributor(BaseModel):
    """One weighted input, carrying its own evidence so the score is explainable."""

    key: str
    label: str
    value: float | None = None
    unit: str = ""
    baseline: float | None = None
    percentage_change: float | None = None
    sub_score: int = Field(0, ge=0, le=100, description="This factor's own 0-100 contribution.")
    weight: float = 0.0
    trend: Literal["up", "down", "stable"] = "stable"
    detail: str = ""


class TimelinePoint(BaseModel):
    minute_offset: int
    clock: str
    drowsiness_score: int
    level: Level


class Episode(BaseModel):
    started_at: str
    ended_at: str
    peak_score: int
    level: Level
    duration_minutes: int


class DrowsinessAssessment(BaseModel):
    assessment_id: str
    user_id: str
    incident_at: str
    window_minutes: int
    drowsiness_score: int = Field(ge=0, le=100, description="Higher means more drowsy.")
    level: Level
    confidence: int = Field(ge=0, le=100)
    contributors: list[Contributor] = Field(default_factory=list)
    timeline: list[TimelinePoint] = Field(default_factory=list)
    episodes: list[Episode] = Field(default_factory=list)
    evidence_summary: str = ""
    low_confidence: bool = False
    disclaimer: str = DROWSINESS_DISCLAIMER
    schema_version: str = "1.0"


def _level_for(score: int) -> Level:
    for threshold, level in _LEVEL_BANDS:
        if score >= threshold:
            return level
    return "alert"


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _circadian_risk(minute_of_day: int) -> tuple[int, str]:
    """Fatigue-risk sub-score from time of day.

    Two well-established troughs: the deep circadian low overnight (02:00-06:00) and the
    weaker post-prandial dip in the early afternoon (13:00-15:00).
    """
    hour = (minute_of_day % 1440) / 60.0
    if 2.0 <= hour < 6.0:
        return 95, "overnight circadian low (02:00-06:00), the highest-risk driving window"
    if 6.0 <= hour < 8.0:
        return 70, "early morning, shortly after waking — sleep inertia window"
    if 13.0 <= hour < 15.0:
        return 55, "post-prandial afternoon dip (13:00-15:00)"
    if 0.0 <= hour < 2.0 or 22.0 <= hour <= 24.0:
        return 75, "late night, extended time awake"
    return 20, "daytime hours outside the recognised circadian troughs"


def _mean_of(records: list[CanonicalDailyRecord], attr: str, days: int = 30) -> float | None:
    vals = [float(v) for r in records[-days:] if (v := getattr(r, attr, None)) is not None]
    return statistics.mean(vals) if vals else None


def assess_drowsiness(
    profile: UserProfile | dict[str, Any],
    incident_at: str | datetime,
    *,
    window_minutes: int = 120,
    continuous_drive_minutes: int = 0,
) -> DrowsinessAssessment:
    """Assess fatigue risk for a driving incident.

    Args:
        profile:                  A ``UserProfile`` or raw profile dict.
        incident_at:              ISO-8601 local datetime of the incident.
        window_minutes:           Intraday window ending at the incident to reconstruct.
        continuous_drive_minutes: Drive duration before the incident, if known.
    """
    if isinstance(profile, dict):
        profile = normalize_profile(profile)

    moment = (
        datetime.fromisoformat(incident_at) if isinstance(incident_at, str) else incident_at
    )
    incident_date: date = moment.date()
    minute_of_day = moment.hour * 60 + moment.minute

    ordered = sorted(profile.records, key=lambda r: r.date)
    # The night before the incident is the record dated on/just before the incident day.
    prior = [r for r in ordered if r.date <= incident_date]
    last_night = prior[-1] if prior else None
    history = prior[:-1] if len(prior) > 1 else []

    contributors: list[Contributor] = []

    # ── 1. Cumulative sleep debt over the trailing week ───────────────────────
    week = prior[-7:]
    debts = [
        _TARGET_SLEEP_MINUTES - r.sleep_duration_minutes
        for r in week
        if r.sleep_duration_minutes is not None
    ]
    debt_total = sum(d for d in debts if d > 0)
    # 600 min (10 h) of accumulated deficit over a week saturates the sub-score.
    debt_score = int(_clamp(100 * debt_total / 600.0))
    contributors.append(
        Contributor(
            key="prior_sleep_debt_min",
            label="Cumulative sleep debt (7 days)",
            value=float(debt_total),
            unit="min",
            baseline=0.0,
            sub_score=debt_score,
            weight=_WEIGHTS["prior_sleep_debt_min"],
            trend="up" if debt_total > 0 else "stable",
            detail=(
                f"{int(debt_total)} min of accumulated shortfall against a "
                f"{_TARGET_SLEEP_MINUTES}-min nightly target across {len(debts)} nights with data."
            ),
        )
    )

    # ── 2. Last night's sleep duration ────────────────────────────────────────
    last_sleep = last_night.sleep_duration_minutes if last_night else None
    mean_sleep = _mean_of(history, "sleep_duration_minutes")
    if last_sleep is not None:
        # 5 h or less saturates; 8 h or more scores zero.
        sleep_score = int(_clamp(100 * (480 - last_sleep) / 180.0))
        pct = (
            round(100 * (last_sleep - mean_sleep) / mean_sleep, 1)
            if mean_sleep
            else None
        )
        contributors.append(
            Contributor(
                key="sleep_duration_last_night",
                label="Sleep the night before",
                value=float(last_sleep),
                unit="min",
                baseline=round(mean_sleep, 1) if mean_sleep else None,
                percentage_change=pct,
                sub_score=sleep_score,
                weight=_WEIGHTS["sleep_duration_last_night"],
                trend="down" if pct is not None and pct < 0 else "stable",
                detail=(
                    f"{last_sleep // 60}h {last_sleep % 60:02d}m slept"
                    + (f", {abs(pct):.0f}% {'below' if pct < 0 else 'above'} the 30-day mean."
                       if pct is not None else ".")
                ),
            )
        )

    # ── 3. HRV suppression vs the member's own baseline ───────────────────────
    last_hrv = last_night.hrv_rmssd_ms if last_night else None
    mean_hrv = _mean_of(history, "hrv_rmssd_ms")
    if last_hrv is not None and mean_hrv:
        drop_pct = round(100 * (mean_hrv - last_hrv) / mean_hrv, 1)
        # A 40% suppression saturates the sub-score.
        contributors.append(
            Contributor(
                key="hrv_drop_pct",
                label="HRV suppression vs baseline",
                value=float(last_hrv),
                unit="ms",
                baseline=round(mean_hrv, 1),
                percentage_change=-drop_pct,
                sub_score=int(_clamp(100 * drop_pct / 40.0)),
                weight=_WEIGHTS["hrv_drop_pct"],
                trend="down" if drop_pct > 0 else "up",
                detail=(
                    f"HRV {last_hrv:.0f} ms against a {mean_hrv:.0f} ms baseline "
                    f"({drop_pct:+.0f}% change) — a recovery-deficit indicator."
                ),
            )
        )

    # ── 4. Resting-HR elevation ───────────────────────────────────────────────
    last_rhr = last_night.resting_hr if last_night else None
    mean_rhr = _mean_of(history, "resting_hr")
    if last_rhr is not None and mean_rhr:
        delta = round(last_rhr - mean_rhr, 1)
        contributors.append(
            Contributor(
                key="resting_hr_delta",
                label="Resting HR vs baseline",
                value=float(last_rhr),
                unit="bpm",
                baseline=round(mean_rhr, 1),
                percentage_change=round(100 * delta / mean_rhr, 1),
                sub_score=int(_clamp(100 * delta / 10.0)),  # +10 bpm saturates
                weight=_WEIGHTS["resting_hr_delta"],
                trend="up" if delta > 0 else "down",
                detail=f"Resting HR {last_rhr} bpm, {delta:+.1f} bpm against baseline.",
            )
        )

    # ── 5. Circadian timing of the incident ───────────────────────────────────
    circ_score, circ_detail = _circadian_risk(minute_of_day)
    contributors.append(
        Contributor(
            key="time_of_day_circadian_risk",
            label="Time-of-day risk",
            value=float(minute_of_day),
            unit="min-of-day",
            sub_score=circ_score,
            weight=_WEIGHTS["time_of_day_circadian_risk"],
            detail=f"Incident at {moment.strftime('%H:%M')} — {circ_detail}.",
        )
    )

    # ── 6. Continuous time at the wheel ───────────────────────────────────────
    contributors.append(
        Contributor(
            key="continuous_drive_minutes",
            label="Continuous driving before incident",
            value=float(continuous_drive_minutes),
            unit="min",
            sub_score=int(_clamp(100 * continuous_drive_minutes / 180.0)),  # 3 h saturates
            weight=_WEIGHTS["continuous_drive_minutes"],
            trend="up" if continuous_drive_minutes > 0 else "stable",
            detail=(
                f"{continuous_drive_minutes} min at the wheel without a recorded break."
                if continuous_drive_minutes
                else "No continuous-driving duration reported."
            ),
        )
    )

    # ── Weighted composite over the contributors we could actually compute ────
    weight_total = sum(c.weight for c in contributors)
    score = (
        int(round(sum(c.sub_score * c.weight for c in contributors) / weight_total))
        if weight_total
        else 0
    )
    level = _level_for(score)

    # Confidence reflects how much of the weight model had real data behind it, tapered
    # by how much history exists to form baselines.
    coverage = weight_total / sum(_WEIGHTS.values())
    history_factor = min(1.0, len(prior) / 30.0)
    confidence = int(round(100 * (0.55 * coverage + 0.45 * history_factor)))

    # ── Intraday timeline, reconstructed from the simulator in `drowsy` context ──
    baselines = live_baselines(
        {
            "resting_hr": last_night.resting_hr if last_night else None,
            "hrv_rmssd_ms": last_night.hrv_rmssd_ms if last_night else None,
        }
    )
    timeline: list[TimelinePoint] = []
    steps = max(1, window_minutes // _SAMPLE_STEP_MINUTES)
    for i in range(steps + 1):
        offset = -window_minutes + i * _SAMPLE_STEP_MINUTES
        minute = (minute_of_day + offset) % 1440
        sample = fetch_latest_sample(baselines, minute, "drowsy")
        # Blend the standing risk with the sampled HRV suppression at that minute, and
        # ramp toward the incident so the curve tells the story of the drive.
        hrv_now = float(sample["hrv"])
        hrv_ref = baselines["hrv"] or hrv_now
        intraday = _clamp(100 * (hrv_ref - hrv_now) / max(hrv_ref * 0.4, 1e-6))
        ramp = 0.65 + 0.35 * (i / steps)
        point_score = int(_clamp(round((0.7 * score + 0.3 * intraday) * ramp)))
        timeline.append(
            TimelinePoint(
                minute_offset=offset,
                clock=sample["clock"],
                drowsiness_score=point_score,
                level=_level_for(point_score),
            )
        )

    # ── Episodes: contiguous runs at or above the moderate threshold ──────────
    episodes: list[Episode] = []
    run: list[TimelinePoint] = []

    def close_run() -> None:
        if not run:
            return
        peak = max(p.drowsiness_score for p in run)
        episodes.append(
            Episode(
                started_at=run[0].clock,
                ended_at=run[-1].clock,
                peak_score=peak,
                level=_level_for(peak),
                duration_minutes=(len(run) - 1) * _SAMPLE_STEP_MINUTES or _SAMPLE_STEP_MINUTES,
            )
        )
        run.clear()

    for point in timeline:
        if point.drowsiness_score >= MODERATE_THRESHOLD:
            run.append(point)
        else:
            close_run()
    close_run()

    top = sorted(
        (c for c in contributors if c.sub_score > 0),
        key=lambda c: c.sub_score * c.weight,
        reverse=True,
    )[:3]
    summary = (
        f"Fatigue risk assessed as {level} ({score}/100) at {moment.strftime('%H:%M')} on "
        f"{incident_date.isoformat()}."
    )
    if top:
        summary += " Principal factors: " + "; ".join(c.label.lower() for c in top) + "."
    if episodes:
        summary += (
            f" {len(episodes)} episode(s) at or above the moderate threshold in the "
            f"{window_minutes} min before the incident."
        )

    return DrowsinessAssessment(
        assessment_id=f"drw_{profile.user_id}_{moment.strftime('%Y%m%dT%H%M')}",
        user_id=profile.user_id,
        incident_at=moment.isoformat(timespec="minutes"),
        window_minutes=window_minutes,
        drowsiness_score=score,
        level=level,
        confidence=confidence,
        contributors=contributors,
        timeline=timeline,
        episodes=episodes,
        evidence_summary=summary,
        low_confidence=confidence < 60 or len(prior) < 14,
    )
