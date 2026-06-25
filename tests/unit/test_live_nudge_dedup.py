"""Unit tests for episode de-duplication + cooldown re-raise (FR-010, FR-016)."""

from __future__ import annotations

from wearable_insights.live_anomaly import filter_new_anomalies
from wearable_insights.models import Anomaly, AnomalyCode, AnomalySeverity, AnomalyTheme


def _anomaly() -> Anomaly:
    return Anomaly(
        code=AnomalyCode.hr_elevated,
        theme=AnomalyTheme.stress,
        severity=AnomalySeverity.moderate,
        signals=["hr"],
        evaluation_tag="Significantly Elevated",
        detail="heart rate trend",
    )


def test_episode_dedup_and_cooldown_reraise() -> None:
    a = _anomaly()
    state: dict = {}

    # First detection → raised.
    new, state = filter_new_anomalies([a], state, now=1000.0, cooldown=600)
    assert [n.code for n in new] == [AnomalyCode.hr_elevated]

    # Persisting across syncs → suppressed (not duplicated). FR-010.
    new, state = filter_new_anomalies([a], state, now=1010.0, cooldown=600)
    assert new == []
    new, state = filter_new_anomalies([a], state, now=1020.0, cooldown=600)
    assert new == []

    # Anomaly clears (absent this sync) → episode ends.
    new, state = filter_new_anomalies([], state, now=1030.0, cooldown=600)
    assert new == []
    assert state["hr_elevated"]["active"] is False

    # Recurs within cooldown (1100 - 1000 = 100 < 600) → still suppressed. FR-016.
    new, state = filter_new_anomalies([a], state, now=1100.0, cooldown=600)
    assert new == []

    # Recurs after cooldown elapsed (1700 - 1000 = 700 ≥ 600) → re-raised. FR-016.
    new, state = filter_new_anomalies([a], state, now=1700.0, cooldown=600)
    assert [n.code for n in new] == [AnomalyCode.hr_elevated]


def test_distinct_codes_tracked_independently() -> None:
    hr = _anomaly()
    hrv = Anomaly(
        code=AnomalyCode.hrv_depressed,
        theme=AnomalyTheme.recovery,
        severity=AnomalySeverity.significant,
        signals=["hrv"],
        evaluation_tag="Significantly Depressed",
        detail="hrv trend",
    )
    state: dict = {}
    new, state = filter_new_anomalies([hr], state, now=1000.0, cooldown=600)
    assert len(new) == 1
    # A new, different code raises even though hr is already active.
    new, state = filter_new_anomalies([hr, hrv], state, now=1005.0, cooldown=600)
    assert [n.code for n in new] == [AnomalyCode.hrv_depressed]
