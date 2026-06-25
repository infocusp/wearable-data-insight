"""Runtime configuration — reads from environment, exposes typed constants.

All thresholds and text constants used by the deterministic layers live here so
golden tests that depend on exact values only need one import to stay in sync.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the repo root (two levels up from this file); silently skipped if absent.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

# ── LLM settings ──────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY")

# GCP project config for Vertex AI (replaces API key auth).
GCP_PROJECT: str | None = os.getenv("GCP_PROJECT")
GCP_LOCATION: str = os.getenv("GCP_LOCATION", "us-central1")

# Default model — override via WEARABLE_MODEL env var.
WEARABLE_MODEL: str = os.getenv("WEARABLE_MODEL", "gemini-2.5-flash-lite")

# All supported models with their provider and required config env var.
MODEL_OPTIONS: dict[str, dict] = {
    "gemini-2.5-flash-lite": {
        "display_name": "Gemini 2.5 Flash Lite",
        "provider": "google",
        "api_key_env": "GCP_PROJECT",
    },
    "gemini-2.5-pro": {
        "display_name": "Gemini 2.5 Pro",
        "provider": "google",
        "api_key_env": "GCP_PROJECT",
    },
    "claude-sonnet-4-6": {
        "display_name": "Claude Sonnet 4.6",
        "provider": "anthropic",
        "api_key_env": "ANTHROPIC_API_KEY",
    },
    "claude-haiku-4-5-20251001": {
        "display_name": "Claude Haiku 4.5",
        "provider": "anthropic",
        "api_key_env": "ANTHROPIC_API_KEY",
    },
}


def get_api_key_for_model(model: str) -> str | None:
    """Return the auth credential for the given model's provider, or None if not set."""
    info = MODEL_OPTIONS.get(model, {})
    env_var = info.get("api_key_env")
    if env_var == "GCP_PROJECT":
        return GCP_PROJECT
    if env_var == "ANTHROPIC_API_KEY":
        return ANTHROPIC_API_KEY
    return None

# ── Analytics thresholds ──────────────────────────────────────────────────────

TREND_THRESHOLD_PCT: float = 15.0   # ±15 % dead-band (FR-008)
CRITICAL_THRESHOLD_PCT: float = 50.0  # |Δ| ≥ 50 % → Critically * tag

# ── Synthetic data defaults ───────────────────────────────────────────────────

DEFAULT_SEED: int = 42
DEFAULT_HISTORY_DAYS: int = 90

# ── Safety / presentation ─────────────────────────────────────────────────────

DISCLAIMER: str = (
    "This information is for general wellness purposes only and is not a substitute "
    "for professional medical advice, diagnosis, or treatment. "
    "Always consult a qualified healthcare provider with any questions about your health."
)

MAX_INSIGHT_RETRIES: int = 2  # attempts after the first before giving up

# ── Phase 2: Anomaly nudges & chat ────────────────────────────────────────────

MAX_NUDGES_PER_DAY: int = int(os.getenv("MAX_NUDGES_PER_DAY", "3"))

# Anomaly severity thresholds (absolute % deviation from 30-day baseline).
# 15–29 % → moderate, 30–49 % → significant, ≥ 50 % → critical.
ANOMALY_MODERATE_PCT: float = float(os.getenv("ANOMALY_MODERATE_PCT", str(TREND_THRESHOLD_PCT)))
ANOMALY_SIGNIFICANT_PCT: float = float(os.getenv("ANOMALY_SIGNIFICANT_PCT", "30.0"))
# Critical boundary reuses the existing CRITICAL_THRESHOLD_PCT (50 %).

# Chat model — defaults to WEARABLE_MODEL; override via WEARABLE_CHAT_MODEL.
CHAT_MODEL: str = os.getenv("WEARABLE_CHAT_MODEL", WEARABLE_MODEL)

# ── Live signals feed (presentation-only) ─────────────────────────────────────
# The dashboard's live panel models *polling a wearable API* (e.g. Fitbit), not a
# per-second stream. These knobs control that cadence. They never affect the
# deterministic analytics/LLM pipeline — the live layer is purely cosmetic.

# Wall-clock seconds between dashboard "syncs" (st.fragment run_every). This is the
# *default* shown in the sidebar's "Sync interval" control; the live value is read from
# session state (``live_fetch_interval``) so it can be changed at runtime.
LIVE_FETCH_INTERVAL_SECS: float = float(os.getenv("LIVE_FETCH_INTERVAL_SECS", "5"))
# Simulated device-time minutes advanced per sync (intraday sample granularity).
DEVICE_SAMPLE_MINUTES: int = int(os.getenv("DEVICE_SAMPLE_MINUTES", "5"))
# How many recent samples the live buffer retains (≈ window length / cadence).
LIVE_BUFFER_POINTS: int = int(os.getenv("LIVE_BUFFER_POINTS", "48"))

# ── Feature 003: live-stream-driven automatic nudges ──────────────────────────
# The live buffer now feeds a deterministic live-anomaly detector (live_anomaly.py).
# Detection is still pure, seeded Python; the LLM only interprets a synthesized
# comparison object (constitution Principle I).  These knobs control the detector
# and the de-duplication / cooldown of auto-nudges.

# Trailing samples averaged when judging a "sustained" live deviation (≈30 min
# device time at DEVICE_SAMPLE_MINUTES=5).  A windowed mean suppresses single-sample
# sensor noise so transient spikes do not raise an anomaly (FR-005).
LIVE_ANOMALY_WINDOW: int = int(os.getenv("LIVE_ANOMALY_WINDOW", "6"))
# Minimum present samples in the window required to evaluate a signal at all.
LIVE_ANOMALY_MIN_SAMPLES: int = int(os.getenv("LIVE_ANOMALY_MIN_SAMPLES", "4"))
# Minimum wall-clock gap before a cleared-then-recurred anomaly may re-raise (FR-016).
NUDGE_COOLDOWN_SECS: float = float(os.getenv("NUDGE_COOLDOWN_SECS", "600"))

# ── Feature 004: slotted time-of-day live baselines ──────────────────────────
# The live-anomaly detector now compares the trailing window mean against the
# historical average for the *current* 3-hour slot (8 slots × weekday/weekend).
# History is synthesized from the existing diurnal model; fully reproducible.

BASELINE_SLOT_COUNT: int = 8
BASELINE_SLOT_WIDTH_MINUTES: int = 180          # 3 hours per slot
BASELINE_HORIZONS: tuple[int, ...] = (7, 30)    # days; maps to weekly / monthly windows
BASELINE_MIN_SAMPLES: int = int(os.getenv("BASELINE_MIN_SAMPLES", "3"))
BASELINE_HISTORY_DAYS: int = int(os.getenv("BASELINE_HISTORY_DAYS", "60"))
BASELINE_SEED: int = int(os.getenv("BASELINE_SEED", "42"))
BASELINE_SAMPLE_STEP_MINUTES: int = int(os.getenv("BASELINE_SAMPLE_STEP_MINUTES", "5"))

# ── Phase 3: Persistent chat history & agent memory ───────────────────────────
# Persistence deviates from the original "stateless" stance (see constitution
# Principle VI, amended) so the dashboard can offer a browsable chat history and
# carry lightweight memory across conversations.

_DATA_DIR = Path(os.getenv("WEARABLE_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data")))

# Single-file SQLite store for chat sessions, turns, and per-user memory.
CHAT_DB_PATH: Path = Path(os.getenv("WEARABLE_CHAT_DB", str(_DATA_DIR / "wearable_chat.db")))

# How many recent conversation summaries to fold into the memory block.
MEMORY_MAX_SUMMARIES: int = int(os.getenv("MEMORY_MAX_SUMMARIES", "5"))
# How many durable user facts to carry forward.
MEMORY_MAX_FACTS: int = int(os.getenv("MEMORY_MAX_FACTS", "12"))
# Lookback window (days) for deterministic recurring-pattern detection.
MEMORY_PATTERN_LOOKBACK_DAYS: int = int(os.getenv("MEMORY_PATTERN_LOOKBACK_DAYS", "7"))
