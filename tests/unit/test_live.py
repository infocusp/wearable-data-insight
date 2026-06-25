"""Unit tests for the presentation-only live vitals feed simulator."""

from __future__ import annotations

from wearable_insights.data import live


def test_baselines_derive_from_record() -> None:
    record = {"resting_hr": 50, "hrv_rmssd_ms": 60.0}
    b = live.live_baselines(record)
    assert b["hr"] == 62.0  # resting + 12 awake bump
    assert b["hrv"] == 60.0
    # Missing record falls back to sane defaults without raising.
    fallback = live.live_baselines(None)
    assert fallback["hr"] == 72.0
    assert set(fallback) == {"hr", "hrv", "spo2", "skin_temp", "resp_rate"}


def test_sample_is_deterministic_and_within_limits() -> None:
    b = live.live_baselines({"resting_hr": 58, "hrv_rmssd_ms": 55.0})
    a = live.fetch_latest_sample(b, 8 * 60, "resting")
    again = live.fetch_latest_sample(b, 8 * 60, "resting")
    assert a == again  # seeded by (device_minute, mode)

    for sig in live.LIVE_SIGNALS:
        lo, hi = live._LIMITS[sig["key"]]
        assert lo <= a[sig["key"]] <= hi
    assert a["clock"] == "08:00"


def test_mode_shifts_raise_heart_rate() -> None:
    b = live.live_baselines({"resting_hr": 58, "hrv_rmssd_ms": 55.0})
    resting = live.fetch_latest_sample(b, 9 * 60, "resting")
    active = live.fetch_latest_sample(b, 9 * 60, "active")
    assert active["hr"] > resting["hr"]
    assert active["hrv"] < resting["hrv"]


def test_signal_status_bands() -> None:
    assert live.signal_status("hr", 70) == "ok"
    assert live.signal_status("hr", 210) == "crit"
    assert live.signal_status("hr", None) == "neutral"


def test_seed_buffer_length_and_clock_order() -> None:
    b = live.live_baselines(None)
    buf = live.seed_buffer(b, "resting", 8 * 60, n=12, step=5)
    assert len(buf) == 12
    assert buf[-1]["clock"] == "08:00"
    assert buf[0]["minute"] < buf[-1]["minute"]
