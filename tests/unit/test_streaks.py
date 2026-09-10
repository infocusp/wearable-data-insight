"""Unit: wellness streaks and reward tiers.

Key behaviours: healthy is judged against the member's *own* trailing baseline with an
absolute floor, missing sensor days are neutral rather than streak-breaking, and the
service reports discount *eligibility* only.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from wearable_insights.data.synthetic import generate_synthetic_profile
from wearable_insights.wellness.streaks import compute_streaks

END = date(2026, 8, 25)


def _streaks(persona: str, days: int = 90):
    profile = generate_synthetic_profile(persona, seed=42, days=days, end_date=END)
    return compute_streaks(profile, END)


def _profile(rows: list[dict]) -> dict:
    return {"user_id": "usr_test", "records": rows}


def _day(offset: int, **overrides) -> dict:
    base = {
        "user_id": "usr_test",
        "date": (END - timedelta(days=offset)).isoformat(),
        "sleep_duration_minutes": 460,
        "sleep_score": 80,
        "resting_hr": 58,
        "hrv_rmssd_ms": 80.0,
        "steps": 9000,
        "active_minutes": 40,
    }
    base.update(overrides)
    return base


def test_deterministic():
    assert _streaks("healthy_consistent").model_dump() == _streaks(
        "healthy_consistent"
    ).model_dump()


def test_consistent_persona_reaches_a_discount_eligible_tier():
    result = _streaks("healthy_consistent")
    assert result.current_streak >= 30
    assert result.tier in {"Gold", "Platinum"}
    assert result.discount_eligible
    assert result.discount_pct_suggested > 0


def test_reports_eligibility_not_an_applied_discount():
    """The engine must never present a discount as granted — that needs human approval."""
    result = _streaks("healthy_consistent")
    assert any("human approval" in r for r in result.rationale)


def test_an_acute_collapse_breaks_the_current_streak_but_not_the_record():
    """recovery_deficit runs clean for 89 days then collapses on the last one."""
    result = _streaks("recovery_deficit")
    assert result.current_streak == 0
    assert result.longest_streak > 50


def test_missing_data_days_are_neutral_not_breaking():
    rows = [_day(o) for o in range(9, 0, -1)]
    # Blank every pillar for one mid-window day — a full sensor outage.
    rows[4] = _day(
        5,
        sleep_duration_minutes=None,
        sleep_score=None,
        resting_hr=None,
        hrv_rmssd_ms=None,
        steps=None,
        active_minutes=None,
    )
    result = compute_streaks(_profile(rows), END)
    states = {d.date.isoformat(): d.state for d in result.days}
    assert states[(END - timedelta(days=5)).isoformat()] == "neutral"
    # The outage must not reset the streak: 8 green days survive around it.
    assert result.current_streak >= 8


def test_a_bad_day_does_break_the_streak():
    rows = [_day(o) for o in range(9, 0, -1)]
    rows[4] = _day(5, steps=500, active_minutes=2)
    result = compute_streaks(_profile(rows), END)
    assert result.current_streak <= 5


def test_low_baseline_cannot_earn_a_streak_on_consistency_alone():
    """Consistently 1,200 steps is consistent, but the absolute floor must still fail it."""
    rows = [_day(o, steps=1200, active_minutes=5) for o in range(14, 0, -1)]
    result = compute_streaks(_profile(rows), END)
    assert result.pillar_streaks["activity"] == 0


def test_next_tier_guidance_is_present_below_the_top():
    result = _streaks("low_activity")
    assert result.next_tier is not None
    assert result.days_to_next_tier is not None and result.days_to_next_tier > 0
