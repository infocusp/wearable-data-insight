"""Streak and reward-tier computation (ClaimGuard integration, stage A).

This lives in Python rather than in the ClaimGuard TypeScript because "healthy" is
defined **relative to the member's own trailing baseline**, and that baseline must be the
same one the nudge detector uses.  Reimplementing it in TS would fork the definition and
let the rewards branch and the risk branch disagree about the same day.

The two branches of the engagement pipeline share this computation:
  * positive consistency  → reward tiers / discount eligibility (here)
  * risk-direction deviation → nudges (``anomaly.py`` → ``nudges.py``)

**Eligibility, never an applied discount.**  This module reports that a member has met a
threshold; granting the discount is a separate, human-approved record on the caller's
side.
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..models import CanonicalDailyRecord, UserProfile
from ..normalize import normalize_profile

Pillar = Literal["activity", "sleep", "recovery"]
DayState = Literal["green", "amber", "neutral"]

PILLARS: tuple[Pillar, ...] = ("activity", "sleep", "recovery")

# Absolute floors, applied alongside the relative-to-own-baseline test so that a member
# whose baseline is itself very low cannot earn a streak purely by being consistent.
_STEPS_FLOOR = 6000
_ACTIVE_MINUTES_FLOOR = 30
_SLEEP_MINUTES_FLOOR = 420  # 7 hours

# Reward ladder. Gold is where discount eligibility begins.
_TIERS: tuple[tuple[int, str, bool], ...] = (
    (7, "Bronze", False),
    (14, "Silver", False),
    (30, "Gold", True),
    (60, "Platinum", True),
)

_DISCOUNT_PCT = {"Bronze": 0, "Silver": 0, "Gold": 5, "Platinum": 10}

# A missing-data day is *neutral*: it neither extends nor breaks a streak. The synthetic
# generator deliberately injects sensor gaps, so treating a gap as a break would end
# every streak within a week and make the whole feature look broken.
_MAX_CONSECUTIVE_NEUTRAL = 2


class PillarFlags(BaseModel):
    activity: DayState = "neutral"
    sleep: DayState = "neutral"
    recovery: DayState = "neutral"


class StreakDay(BaseModel):
    date: date
    state: DayState
    pillars: PillarFlags
    detail: str = ""


class StreakSet(BaseModel):
    user_id: str
    analysis_date: date
    lookback_days: int
    current_streak: int
    longest_streak: int
    pillar_streaks: dict[str, int] = Field(default_factory=dict)
    days: list[StreakDay] = Field(default_factory=list)
    tier: str | None = None
    next_tier: str | None = None
    days_to_next_tier: int | None = None
    discount_eligible: bool = False
    discount_pct_suggested: int = 0
    rationale: list[str] = Field(default_factory=list)
    schema_version: str = "1.0"


def _trailing_mean(
    records: list[CanonicalDailyRecord], upto: date, attr: str, days: int = 30
) -> float | None:
    """Mean of *attr* over the ``days`` records strictly before *upto*."""
    window = [r for r in records if r.date < upto][-days:]
    vals = [float(v) for r in window if (v := getattr(r, attr, None)) is not None]
    return statistics.mean(vals) if vals else None


def _pillar_state(
    record: CanonicalDailyRecord,
    records: list[CanonicalDailyRecord],
    pillar: Pillar,
) -> DayState:
    """Judge one pillar for one day against the member's own trailing 30-day mean."""
    if pillar == "activity":
        steps, active = record.steps, record.active_minutes
        if steps is None and active is None:
            return "neutral"
        mean_steps = _trailing_mean(records, record.date, "steps")
        target = max(0.9 * mean_steps, _STEPS_FLOOR) if mean_steps else _STEPS_FLOOR
        if (steps is not None and steps >= target) or (
            active is not None and active >= _ACTIVE_MINUTES_FLOOR
        ):
            return "green"
        return "amber"

    if pillar == "sleep":
        duration, score = record.sleep_duration_minutes, record.sleep_score
        if duration is None and score is None:
            return "neutral"
        mean_dur = _trailing_mean(records, record.date, "sleep_duration_minutes")
        long_enough = duration is not None and (
            duration >= _SLEEP_MINUTES_FLOOR
            or (mean_dur is not None and duration >= 0.95 * mean_dur)
        )
        # A collapsed sleep score vetoes the pillar even when duration looks fine.
        mean_score = _trailing_mean(records, record.date, "sleep_score")
        score_ok = not (
            score is not None and mean_score is not None and score < 0.5 * mean_score
        )
        return "green" if long_enough and score_ok else "amber"

    # recovery
    hrv, rhr = record.hrv_rmssd_ms, record.resting_hr
    if hrv is None and rhr is None:
        return "neutral"
    mean_hrv = _trailing_mean(records, record.date, "hrv_rmssd_ms")
    mean_rhr = _trailing_mean(records, record.date, "resting_hr")
    hrv_ok = hrv is None or mean_hrv is None or hrv >= 0.9 * mean_hrv
    rhr_ok = rhr is None or mean_rhr is None or rhr <= 1.1 * mean_rhr
    return "green" if hrv_ok and rhr_ok else "amber"


def _day_state(flags: PillarFlags) -> DayState:
    """A day is green when every pillar that *has* data is green."""
    states = [getattr(flags, p) for p in PILLARS]
    judged = [s for s in states if s != "neutral"]
    if not judged:
        return "neutral"
    return "green" if all(s == "green" for s in judged) else "amber"


def _tier_for(streak: int) -> tuple[str | None, str | None, int | None, bool]:
    """Return (tier, next_tier, days_to_next, discount_eligible) for a streak length."""
    earned: str | None = None
    eligible = False
    for threshold, name, discount in _TIERS:
        if streak >= threshold:
            earned, eligible = name, discount
    nxt = next(((t, n) for t, n, _ in _TIERS if streak < t), None)
    if nxt is None:
        return earned, None, None, eligible
    return earned, nxt[1], nxt[0] - streak, eligible


def compute_streaks(
    profile: UserProfile | dict[str, Any],
    analysis_date: date | None = None,
    *,
    lookback_days: int = 90,
) -> StreakSet:
    """Compute streaks, tier, and discount eligibility for one member."""
    if isinstance(profile, dict):
        profile = normalize_profile(profile)

    ordered = sorted(profile.records, key=lambda r: r.date)
    resolved = analysis_date or ordered[-1].date
    window = [r for r in ordered if r.date <= resolved][-lookback_days:]

    days: list[StreakDay] = []
    for record in window:
        flags = PillarFlags(
            **{p: _pillar_state(record, ordered, p) for p in PILLARS}  # type: ignore[arg-type]
        )
        state = _day_state(flags)
        missing = [p for p in PILLARS if getattr(flags, p) == "neutral"]
        detail = f"no data for {', '.join(missing)}" if missing else ""
        days.append(StreakDay(date=record.date, state=state, pillars=flags, detail=detail))

    # ── Streak walk: green extends, amber breaks, neutral tolerated up to a limit ──
    def walk(states: list[DayState]) -> tuple[int, int]:
        current = longest = neutral_run = 0
        for state in states:
            if state == "green":
                current += 1
                neutral_run = 0
            elif state == "neutral":
                neutral_run += 1
                if neutral_run > _MAX_CONSECUTIVE_NEUTRAL:
                    current, neutral_run = 0, 0
            else:
                current, neutral_run = 0, 0
            longest = max(longest, current)
        return current, longest

    current_streak, longest_streak = walk([d.state for d in days])

    pillar_streaks: dict[str, int] = {}
    for pillar in PILLARS:
        pillar_streaks[pillar] = walk([getattr(d.pillars, pillar) for d in days])[0]

    tier, next_tier, to_next, eligible = _tier_for(current_streak)

    rationale = [
        f"{current_streak}-day all-green streak "
        f"({sum(1 for d in days if d.state == 'green')} green of {len(days)} days observed).",
        "A day counts as green when every pillar with available data meets the member's "
        "own trailing 30-day baseline (with absolute floors so a low baseline cannot "
        "qualify on consistency alone).",
    ]
    if any(d.state == "neutral" for d in days):
        rationale.append(
            f"Days with missing sensor data are neutral — they neither extend nor break a "
            f"streak, up to {_MAX_CONSECUTIVE_NEUTRAL} consecutive days."
        )
    if eligible:
        rationale.append(
            f"{tier} tier meets the discount-eligibility threshold. Eligibility only — "
            "applying a premium change requires separate human approval."
        )

    return StreakSet(
        user_id=profile.user_id,
        analysis_date=resolved,
        lookback_days=lookback_days,
        current_streak=current_streak,
        longest_streak=longest_streak,
        pillar_streaks=pillar_streaks,
        days=days,
        tier=tier,
        next_tier=next_tier,
        days_to_next_tier=to_next,
        discount_eligible=eligible,
        discount_pct_suggested=_DISCOUNT_PCT.get(tier or "", 0) if eligible else 0,
        rationale=rationale,
    )
