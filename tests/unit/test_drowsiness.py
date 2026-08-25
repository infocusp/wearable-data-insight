"""Unit: driver-drowsiness assessment.

Two things are asserted beyond arithmetic, because they are the point of the feature:

* the full ``alert``/``mild``/``moderate``/``severe`` band is reachable, so the labels
  are meaningful rather than decorative;
* the output frames fatigue as liability/causation context and never as fraud evidence.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from wearable_insights.data.synthetic import generate_synthetic_profile
from wearable_insights.driving.drowsiness import (
    MODERATE_THRESHOLD,
    assess_drowsiness,
)

END = date(2026, 8, 25)


def _synthetic(hist: dict, last: dict, nights: int = 30) -> dict:
    rows = [
        {
            "user_id": "usr_test",
            "date": (END - timedelta(days=nights - i)).isoformat(),
            "sleep_score": 70,
            "steps": 8000,
            "active_minutes": 30,
            **hist,
        }
        for i in range(nights)
    ]
    rows.append({"user_id": "usr_test", "date": END.isoformat(), "sleep_score": 35, **last})
    return {"user_id": "usr_test", "records": rows}


GOOD_HISTORY = {"sleep_duration_minutes": 450, "hrv_rmssd_ms": 80.0, "resting_hr": 58}
ACUTE_COLLAPSE = {
    "sleep_duration_minutes": 180,
    "hrv_rmssd_ms": 40.0,
    "resting_hr": 72,
    "steps": 2000,
    "active_minutes": 5,
}


def test_deterministic():
    profile = generate_synthetic_profile("recovery_deficit", seed=42, days=90, end_date=END)
    a = assess_drowsiness(profile, "2026-08-25T07:40", continuous_drive_minutes=75)
    b = assess_drowsiness(profile, "2026-08-25T07:40", continuous_drive_minutes=75)
    assert a.model_dump() == b.model_dump()


def test_well_rested_daytime_drive_is_alert():
    profile = _synthetic(GOOD_HISTORY, {**GOOD_HISTORY, "sleep_duration_minutes": 470})
    result = assess_drowsiness(profile, f"{END}T13:00", continuous_drive_minutes=20)
    assert result.level == "alert"
    assert result.drowsiness_score < 25
    assert result.episodes == []


def test_worst_case_reaches_severe():
    """Acute collapse on a healthy baseline, circadian trough, long unbroken drive."""
    profile = _synthetic(GOOD_HISTORY, ACUTE_COLLAPSE)
    result = assess_drowsiness(profile, f"{END}T03:30", continuous_drive_minutes=240)
    assert result.level == "severe"
    assert result.drowsiness_score >= 75


def test_circadian_trough_scores_above_the_same_drive_at_midday():
    profile = _synthetic(GOOD_HISTORY, ACUTE_COLLAPSE)
    night = assess_drowsiness(profile, f"{END}T03:30", continuous_drive_minutes=120)
    noon = assess_drowsiness(profile, f"{END}T11:30", continuous_drive_minutes=120)
    assert night.drowsiness_score > noon.drowsiness_score


def test_longer_continuous_drive_increases_the_score():
    profile = _synthetic(GOOD_HISTORY, ACUTE_COLLAPSE)
    short = assess_drowsiness(profile, f"{END}T07:40", continuous_drive_minutes=15)
    long = assess_drowsiness(profile, f"{END}T07:40", continuous_drive_minutes=240)
    assert long.drowsiness_score > short.drowsiness_score


def test_contributors_are_explainable_and_weighted():
    profile = _synthetic(GOOD_HISTORY, ACUTE_COLLAPSE)
    result = assess_drowsiness(profile, f"{END}T03:30", continuous_drive_minutes=180)
    assert result.contributors
    for contributor in result.contributors:
        assert 0 <= contributor.sub_score <= 100
        assert contributor.weight > 0
        assert contributor.detail, f"{contributor.key} has no explanation"
    # The reported score must actually be the weighted mean of its contributors.
    total_weight = sum(c.weight for c in result.contributors)
    expected = round(
        sum(c.sub_score * c.weight for c in result.contributors) / total_weight
    )
    assert result.drowsiness_score == expected


def test_episodes_only_form_at_or_above_the_moderate_threshold():
    profile = _synthetic(GOOD_HISTORY, ACUTE_COLLAPSE)
    result = assess_drowsiness(profile, f"{END}T03:30", continuous_drive_minutes=240)
    for episode in result.episodes:
        assert episode.peak_score >= MODERATE_THRESHOLD
    for point in result.timeline:
        assert 0 <= point.drowsiness_score <= 100


def test_timeline_ends_at_the_incident():
    profile = _synthetic(GOOD_HISTORY, ACUTE_COLLAPSE)
    result = assess_drowsiness(profile, f"{END}T07:40", window_minutes=120)
    assert result.timeline[0].minute_offset == -120
    assert result.timeline[-1].minute_offset == 0


def test_framed_as_fatigue_context_never_as_fraud():
    profile = _synthetic(GOOD_HISTORY, ACUTE_COLLAPSE)
    result = assess_drowsiness(profile, f"{END}T03:30", continuous_drive_minutes=240)
    assert "not fraud" in result.disclaimer.lower()
    assert "human adjuster" in result.disclaimer.lower()
    blob = result.model_dump_json().lower()
    for forbidden in ("fraud" + "ulent", "dishonest", "staged", "misrepresent"):
        assert forbidden not in blob


def test_thin_history_is_reported_as_low_confidence():
    profile = _synthetic(GOOD_HISTORY, ACUTE_COLLAPSE, nights=5)
    result = assess_drowsiness(profile, f"{END}T03:30", continuous_drive_minutes=120)
    assert result.low_confidence
