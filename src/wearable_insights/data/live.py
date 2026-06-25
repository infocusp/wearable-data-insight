"""Live vitals feed simulator — presentation-only.

Models *polling a wearable API* (e.g. Fitbit): each "fetch" returns one reading at
the device's intraday sampling cadence, anchored to the day's deterministic summary
record. This module is deliberately **not** imported by the analytics/LLM pipeline
(``pipeline.py`` / ``comparison.py``); the live layer never influences the
comparison object, nudges, or chat — it only drives the dashboard's live charts.

Sampling is discrete and reproducible (seeded by simulated device time + mode), not
a smooth per-second animation.
"""

from __future__ import annotations

import math
import random
from typing import Any

# Displayed live signals: key, label, unit, "normal" range (for status dot), decimals.
LIVE_SIGNALS: list[dict[str, Any]] = [
    {"key": "hr", "label": "Heart rate", "unit": "bpm", "normal": (55, 100), "dec": 0},
    {"key": "hrv", "label": "HRV (RMSSD)", "unit": "ms", "normal": (20, 140), "dec": 0},
    {"key": "spo2", "label": "SpO₂", "unit": "%", "normal": (95, 100), "dec": 1},
    {"key": "skin_temp", "label": "Skin temp", "unit": "°C", "normal": (35.5, 37.5), "dec": 1},
    {"key": "resp_rate", "label": "Respiration", "unit": "rpm", "normal": (10, 20), "dec": 0},
]

# Per-mode anchor shifts (added to the baseline). Tuned so a context switch produces a
# physiologically plausible, *detectable* trend across all live signals (Feature 003):
# exertion/stress dip SpO₂ slightly and raise skin temp + respiration, not just HR/HRV.
#
# Each context is tuned to surface a different nudge theme deterministically:
#   resting   → nothing fires (within baseline dead-bands)
#   active    → HR elevated (stress theme)
#   stressed  → HRV depressed + HR elevated (recovery + stress)
#   wake-up   → HRV depressed right after sleep → recovery / sleep-quality nudge
#   sedentary → mild HRV depression from prolonged inactivity → low-movement recovery nudge
#   unwell    → SpO₂ low + skin temp & respiration elevated → vitals nudges
_MODE_SHIFT: dict[str, dict[str, float]] = {
    "resting":   {"hr": 0.0,  "hrv": 6.0,   "spo2": 0.2,  "skin_temp": 0.0, "resp_rate": -1.0},
    "active":    {"hr": 28.0, "hrv": -16.0, "spo2": -2.4, "skin_temp": 0.9, "resp_rate": 6.0},
    "stressed":  {"hr": 14.0, "hrv": -22.0, "spo2": -2.0, "skin_temp": 0.7, "resp_rate": 3.0},
    "wake-up":   {"hr": 4.0,  "hrv": -24.0, "spo2": -0.2, "skin_temp": 0.3, "resp_rate": 0.0},
    "sedentary": {"hr": 8.0,  "hrv": -19.0, "spo2": 0.0,  "skin_temp": 0.0, "resp_rate": 0.0},
    "unwell":    {"hr": 12.0, "hrv": -8.0,  "spo2": -3.0, "skin_temp": 1.4, "resp_rate": 4.0},
}
_MODE_IDX = {"resting": 0, "active": 1, "stressed": 2, "wake-up": 3, "sedentary": 4, "unwell": 5}
MODES = ("resting", "active", "stressed", "wake-up", "sedentary", "unwell")

# Slow diurnal oscillation amplitude + per-fetch sensor noise.
_AMPLITUDE = {"hr": 5.0, "hrv": 8.0, "spo2": 0.4, "skin_temp": 0.15, "resp_rate": 1.2}
_NOISE = {"hr": 2.0, "hrv": 3.0, "spo2": 0.2, "skin_temp": 0.08, "resp_rate": 0.6}
_PHASE = {"hr": 0.0, "hrv": 1.3, "spo2": 2.1, "skin_temp": 3.4, "resp_rate": 4.7}
_LIMITS = {
    "hr": (35.0, 190.0), "hrv": (5.0, 200.0), "spo2": (80.0, 100.0),
    "skin_temp": (34.0, 40.0), "resp_rate": (6.0, 36.0),
}


def live_baselines(record: dict | None) -> dict[str, float]:
    """Derive live-signal anchors from today's deterministic daily record."""
    record = record or {}
    resting = record.get("resting_hr") or 60
    hrv = record.get("hrv_rmssd_ms") or 55.0
    return {
        "hr": float(resting) + 12.0,   # awake HR sits above resting
        "hrv": float(hrv),
        "spo2": 97.6,                  # not in the daily record — plausible constant
        "skin_temp": 36.7,
        "resp_rate": 14.0,
    }


def clock_label(minute: int) -> str:
    """Format a minute-of-day as ``HH:MM`` (wraps at midnight)."""
    minute %= 1440
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def fetch_latest_sample(
    baselines: dict[str, float],
    device_minute: int,
    mode: str = "resting",
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Return one reading for the given simulated device timestamp (deterministic)."""
    rng = rng or random.Random(device_minute * 7919 + _MODE_IDX.get(mode, 0) * 104729)
    shift = _MODE_SHIFT.get(mode, _MODE_SHIFT["resting"])
    phase = device_minute / 90.0 * 2.0 * math.pi  # slow ~90-min drift
    sample: dict[str, Any] = {
        "minute": device_minute,
        "clock": clock_label(device_minute),
        "mode": mode,
    }
    for sig in LIVE_SIGNALS:
        key = sig["key"]
        anchor = baselines[key] + shift.get(key, 0.0)
        val = anchor + _AMPLITUDE[key] * math.sin(phase + _PHASE[key]) + rng.gauss(0.0, _NOISE[key])
        lo, hi = _LIMITS[key]
        val = _clamp(val, lo, hi)
        sample[key] = round(val, sig["dec"]) if sig["dec"] else int(round(val))
    return sample


def signal_status(key: str, value: float | None) -> str:
    """Map a value to ``ok`` / ``warn`` / ``crit`` against the signal's normal range."""
    sig = next((s for s in LIVE_SIGNALS if s["key"] == key), None)
    if sig is None or value is None:
        return "neutral"
    lo, hi = sig["normal"]
    if lo <= value <= hi:
        return "ok"
    dist = (lo - value) if value < lo else (value - hi)
    return "warn" if dist <= (hi - lo) * 0.25 else "crit"


def seed_buffer(
    baselines: dict[str, float],
    mode: str,
    start_minute: int,
    n: int,
    step: int,
) -> list[dict[str, Any]]:
    """Pre-fill a rolling buffer with *n* historical samples ending at ``start_minute``."""
    first = start_minute - (n - 1) * step
    return [fetch_latest_sample(baselines, (first + i * step) % 1440, mode) for i in range(n)]
