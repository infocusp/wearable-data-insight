"""Request envelopes for the ClaimGuard-facing HTTP API.

Design rule: **the sidecar owns zero mutable state.**  Every piece of Streamlit
``st.session_state`` is either reconstructible from a seed tuple (``ProfileRef``,
``LiveCursor``) or round-trips through the request/response as JSON (``nudge_state``).
That keeps the service restart-safe and horizontally scalable, and it works because the
engine is already almost entirely pure functions.

Response models are the existing Pydantic classes from ``models.py`` wherever possible,
so FastAPI derives the OpenAPI schema straight from the engine and the two cannot drift.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from .data.live import MODES
from .data.synthetic import PERSONA_NAMES
from .models import Anomaly, ComparisonObject, Nudge, NudgeSet

Persona = Literal[
    "recovery_deficit",
    "healthy_consistent",
    "poor_sleep_week",
    "low_activity",
    "recovery_decline",
]

LiveMode = Literal[
    "resting", "active", "stressed", "wake-up", "sedentary", "unwell", "drowsy"
]

# Fail loudly at import if the literals drift from the engine's own tuples, rather than
# silently rejecting a valid persona/mode at request time.
assert set(Persona.__args__) == set(PERSONA_NAMES), (  # type: ignore[attr-defined]
    f"Persona literal drifted from PERSONA_NAMES: {set(PERSONA_NAMES)}"
)
assert set(LiveMode.__args__) == set(MODES), (  # type: ignore[attr-defined]
    f"LiveMode literal drifted from data.live.MODES: {set(MODES)}"
)


class ProfileRef(BaseModel):
    """A reproducible pointer to a synthetic wearable history.

    This is the whole persistence story for wearable data: ClaimGuard stores these six
    fields on ``WearableProfile`` and the engine reconstructs the identical 90-day series
    on demand.  Nothing about the series itself is ever stored.
    """

    persona: Persona
    user_id: str | None = Field(
        None, description="Caller-scoped id (e.g. 'cg_user_7'); overrides the engine default."
    )
    seed: int = 42
    days: int = Field(90, ge=1, le=400)
    end_date: date = Field(
        ...,
        description=(
            "Last date in the generated series. REQUIRED: the engine must never fall back "
            "to date.today() in a request path, or responses change silently at UTC midnight "
            "and differ between caller and sidecar timezones."
        ),
    )
    jitter: float = Field(0.0, ge=0.0, le=1.0)


class LlmOptions(BaseModel):
    """Per-request model selection for the LLM-backed endpoints."""

    model: str | None = Field(None, description="Must be a key of config.MODEL_OPTIONS.")
    max_retries: int | None = Field(None, ge=0, le=5)
    skip_llm: bool = Field(
        False, description="Run only the deterministic layers and return them."
    )


class AnalyzeRequest(BaseModel):
    profile: ProfileRef
    analysis_date: date | None = Field(
        None, description="Day to analyse; defaults to profile.end_date."
    )
    llm: LlmOptions = Field(default_factory=LlmOptions)

    def resolved_analysis_date(self) -> date:
        return self.analysis_date or self.profile.end_date


class LiveCursor(BaseModel):
    """Position in the simulated intraday feed — replaces the Streamlit deque.

    ``seed_buffer`` is pure, so the whole rolling buffer is reconstructible from these
    five fields.  The response echoes back an *advanced* cursor, so the caller never
    performs clock arithmetic itself.
    """

    mode: LiveMode = "resting"
    device_minute: int = Field(480, ge=0, le=1439, description="Minute-of-day; 480 = 08:00.")
    points: int = Field(48, ge=1, le=288, description="Rolling buffer length.")
    step: int = Field(5, ge=1, le=60, description="Device minutes advanced per sync.")
    day_type: Literal["weekday", "weekend"] | None = Field(
        None, description="Derived from analysis_date when omitted."
    )


class LiveNudgeStateEntry(BaseModel):
    """One anomaly code's episode/cooldown state, keyed by AnomalyCode value."""

    active: bool = False
    last_raised_ts: float | None = None


class LiveTickRequest(BaseModel):
    profile: ProfileRef
    cursor: LiveCursor = Field(default_factory=LiveCursor)
    analysis_date: date | None = None
    nudge_state: dict[str, LiveNudgeStateEntry] = Field(
        default_factory=dict,
        description="Round-tripped episode/cooldown state. Send back what you last received.",
    )
    now: float | None = Field(
        None, description="Caller clock (epoch seconds) for deterministic cooldown in tests."
    )
    generate_nudges: bool = True
    llm: LlmOptions = Field(default_factory=LlmOptions)

    def resolved_analysis_date(self) -> date:
        return self.analysis_date or self.profile.end_date


class UnderwritingRequest(BaseModel):
    profile: ProfileRef
    analysis_date: date | None = None
    window_days: int = Field(90, ge=7, le=400)

    def resolved_analysis_date(self) -> date:
        return self.analysis_date or self.profile.end_date


class StreakRequest(BaseModel):
    profile: ProfileRef
    analysis_date: date | None = None
    lookback_days: int = Field(90, ge=7, le=400)

    def resolved_analysis_date(self) -> date:
        return self.analysis_date or self.profile.end_date


class DrowsinessRequest(BaseModel):
    profile: ProfileRef
    incident_at: str = Field(
        ..., description="ISO-8601 local datetime of the incident, e.g. '2026-08-24T07:40'."
    )
    window_minutes: int = Field(120, ge=30, le=600)
    continuous_drive_minutes: int = Field(
        0, ge=0, le=1440, description="Self-reported/telematics drive duration before the incident."
    )


class ErrorResponse(BaseModel):
    """Matches the error envelope of the existing 001 REST contract."""

    error: str
    detail: str | None = None
    violations: list[str] | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"]
    engine_version: str
    schema_version: str
    default_model: str
    personas: list[str]
    baselines_warm: bool


class PersonaSpec(BaseModel):
    persona: str
    engine_user_id: str
    display_name: str
    dob: str
    age: int | None = None
    gender: str | None = None
    avatar: str


class PersonaListResponse(BaseModel):
    personas: list[PersonaSpec]


class ProfileMeta(BaseModel):
    """Non-metric identity echoed back so callers can render a profile card."""

    user_id: str
    persona: str
    display_name: str | None = None
    dob: str | None = None
    age: int | None = None
    gender: str | None = None
    avatar: str | None = None
    record_count: int
    first_date: date | None = None
    last_date: date | None = None


class LiveSample(BaseModel):
    minute: int
    clock: str
    mode: str
    hr: float | None = None
    hrv: float | None = None
    spo2: float | None = None
    skin_temp: float | None = None
    resp_rate: float | None = None
    status: dict[str, str] = Field(
        default_factory=dict, description="Per-signal ok/warn/crit/neutral."
    )


def sample_to_model(sample: dict[str, Any], statuses: dict[str, str]) -> LiveSample:
    """Adapt a raw ``fetch_latest_sample`` dict into the wire model."""
    return LiveSample(
        minute=sample["minute"],
        clock=sample["clock"],
        mode=sample["mode"],
        hr=sample.get("hr"),
        hrv=sample.get("hrv"),
        spo2=sample.get("spo2"),
        skin_temp=sample.get("skin_temp"),
        resp_rate=sample.get("resp_rate"),
        status=statuses,
    )


# ── Response envelopes ────────────────────────────────────────────────────────
# These reference the engine's own models rather than redescribing them, so the
# published contract is derived from ``models.py`` and the two cannot drift.


class ComparisonResponse(BaseModel):
    comparison: ComparisonObject
    profile_meta: ProfileMeta
    engine_version: str


class NudgeResponse(BaseModel):
    """Note the deliberate 200-with-``error`` contract.

    ``comparison`` is deterministic and useful even when the LLM leg fails, so an upstream
    model outage is reported here rather than as an HTTP error status that would throw the
    analysis away along with the narrative.
    """

    comparison: ComparisonObject
    nudge_set: NudgeSet | None = None
    error: str | None = None
    max_nudges_per_day: int | None = None
    llm_skipped: bool = False


class LiveTickResponse(BaseModel):
    samples: list[LiveSample]
    latest: LiveSample | None = None
    anomalies: list[Anomaly] = Field(default_factory=list)
    new_anomalies: list[Anomaly] = Field(
        default_factory=list, description="Anomalies passing episode/cooldown de-duplication."
    )
    nudges: list[Nudge] = Field(default_factory=list)
    nudge_state: dict[str, LiveNudgeStateEntry] = Field(
        default_factory=dict, description="Persist this and send it back on the next tick."
    )
    cursor: LiveCursor = Field(description="Already advanced — store as-is.")
    slot: int
    slot_label: str
    day_type: Literal["weekday", "weekend"]
    error: str | None = None
