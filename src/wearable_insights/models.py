"""Pydantic v2 canonical models mirroring contracts/ JSON Schemas."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CanonicalDailyRecord(BaseModel):
    """One normalized day of wearable summary data (FR-003, FR-004)."""

    user_id: str
    date: date
    sleep_duration_minutes: int | None = None
    sleep_score: int | None = None
    deep_sleep_minutes: int | None = None
    rem_sleep_minutes: int | None = None
    bedtime: str | None = None  # HH:MM local time
    resting_hr: int | None = None
    hrv_rmssd_ms: float | None = None
    stress_score: int | None = None
    steps: int | None = None
    active_minutes: int | None = None
    missing_fields: list[str] = Field(default_factory=list)
    invalid_fields: list[str] = Field(default_factory=list)


class UserProfile(BaseModel):
    """A user and their time-ordered history of daily records."""

    user_id: str
    age: int | None = None
    gender: str | None = None
    records: list[CanonicalDailyRecord]

    @model_validator(mode="after")
    def _validate_records(self) -> "UserProfile":
        dates = [r.date for r in self.records]
        if dates != sorted(dates):
            raise ValueError("records must be sorted ascending by date")
        if len(dates) != len(set(dates)):
            raise ValueError("records must have unique dates")
        if not self.records:
            raise ValueError("records must contain at least one entry")
        return self


class MetricBaseline(BaseModel):
    """Per-metric reference values for one analysis date (FR-007)."""

    current: float | None = None
    mean_7d: float | None = None
    mean_30d: float | None = None
    mean_60d: float | None = None
    mean_90d: float | None = None
    weekday_mean: float | None = None
    n_days_used: int = 0
    low_confidence: bool = False


class BaselineSet(BaseModel):
    """All tracked metric baselines for one user on one analysis date."""

    user_id: str
    analysis_date: date
    metrics: dict[str, MetricBaseline] = Field(default_factory=dict)


class WindowComparison(BaseModel):
    """Comparison of current value vs. one named baseline window."""

    baseline_value: float | None = None
    percentage_change: float | None = None
    trend: Literal["up", "down", "stable"] = "stable"
    evaluation_tag: Literal[
        "Significantly Elevated",
        "Significantly Depressed",
        "Critically Elevated",
        "Critically Depressed",
        "Stable / Within Normal Baseline",
    ] = "Stable / Within Normal Baseline"


class MetricComparison(BaseModel):
    """Current-vs-baseline comparison for a single metric across windows (FR-009)."""

    current_value: float | None = None
    weekly: WindowComparison = Field(default_factory=WindowComparison)
    monthly: WindowComparison = Field(default_factory=WindowComparison)
    weekday: WindowComparison = Field(default_factory=WindowComparison)
    sixty_day: WindowComparison = Field(default_factory=WindowComparison)
    ninety_day: WindowComparison = Field(default_factory=WindowComparison)
    flags: list[str] = Field(default_factory=list)


class DataQuality(BaseModel):
    missing_fields: list[str] = Field(default_factory=list)
    invalid_fields: list[str] = Field(default_factory=list)
    low_confidence: bool = False


class CandidateAssociation(BaseModel):
    """Non-causal co-occurrence produced by a defined rule (FR-010)."""

    relation: str
    signals: list[str]
    description: str
    kind: Literal["association"] = "association"


class ComparisonObject(BaseModel):
    """Compact, LLM-facing contract between analysis and inference (FR-009)."""

    user_id: str
    analysis_date: date
    sleep: dict[str, MetricComparison] = Field(default_factory=dict)
    heart_health: dict[str, MetricComparison] = Field(default_factory=dict)
    activity: dict[str, MetricComparison] = Field(default_factory=dict)
    candidate_associations: list[CandidateAssociation] = Field(default_factory=list)
    data_quality: DataQuality = Field(default_factory=DataQuality)
    schema_version: str = "1.0"


class Insight(BaseModel):
    """One user-facing, schema-validated insight (FR-013)."""

    title: str
    summary: str
    action: str
    confidence: Literal["low", "medium", "high"]
    source_signals: list[str]


class InsightSet(BaseModel):
    """Full response produced by the LLM and validated by safety.py."""

    insights: list[Insight]
    disclaimer: str
    generated_from: list[str]
    schema_version: str = "1.0"


# ── Phase 2: Anomaly nudges & chat ────────────────────────────────────────────


class AnomalyCode(str, Enum):
    stress_elevated = "stress_elevated"
    steps_low = "steps_low"
    active_minutes_low = "active_minutes_low"
    sleep_insufficient = "sleep_insufficient"
    sleep_quality_low = "sleep_quality_low"
    hrv_depressed = "hrv_depressed"
    # Feature 003: live-stream-driven detection (intraday vitals trend).
    hr_elevated = "hr_elevated"
    spo2_low = "spo2_low"
    skin_temp_elevated = "skin_temp_elevated"
    resp_rate_elevated = "resp_rate_elevated"


class AnomalyTheme(str, Enum):
    sleep = "sleep"
    recovery = "recovery"
    activity = "activity"
    stress = "stress"
    # Feature 003: cardio-respiratory vitals (SpO₂, skin temp, respiration).
    vitals = "vitals"


class AnomalySeverity(str, Enum):
    moderate = "moderate"
    significant = "significant"
    critical = "critical"


_SEVERITY_ORDER: dict[AnomalySeverity, int] = {
    AnomalySeverity.moderate: 0,
    AnomalySeverity.significant: 1,
    AnomalySeverity.critical: 2,
}


class Anomaly(BaseModel):
    """Deterministically detected deviation for one day (FR-002, FR-021)."""

    code: AnomalyCode
    theme: AnomalyTheme
    severity: AnomalySeverity
    signals: list[str] = Field(min_length=1)
    evaluation_tag: str
    detail: str


class Nudge(BaseModel):
    """User-facing item wrapping one Insight, raised from ≥1 anomalies (FR-003, FR-007)."""

    nudge_id: str
    user_id: str
    analysis_date: date
    theme: AnomalyTheme
    severity: AnomalySeverity
    anomalies: list[Anomaly] = Field(min_length=1)
    insight: Insight
    disclaimer: str
    triggered_by: list[str]


class NudgeSet(BaseModel):
    """Bounded daily nudge collection (FR-005, FR-006, SC-008)."""

    user_id: str
    analysis_date: date
    nudges: list[Nudge] = Field(default_factory=list)
    schema_version: str = "1.0"

    @model_validator(mode="after")
    def _enforce_cap(self) -> "NudgeSet":
        from .config import MAX_NUDGES_PER_DAY  # lazy import avoids circular dep

        if len(self.nudges) > MAX_NUDGES_PER_DAY:
            raise ValueError(
                f"NudgeSet has {len(self.nudges)} nudges; "
                f"exceeds MAX_NUDGES_PER_DAY={MAX_NUDGES_PER_DAY}"
            )
        return self


class ChatTurn(BaseModel):
    """One message in a nudge-scoped conversation."""

    role: Literal["user", "assistant"]
    content: str


class ChatGrounding(BaseModel):
    """The only data the chat assistant may reference (FR-009)."""

    nudge: Nudge
    comparison: ComparisonObject


class ChatSession(BaseModel):
    """In-memory, session-scoped conversation bound to one nudge (FR-008, FR-011)."""

    nudge_id: str
    turns: list[ChatTurn] = Field(default_factory=list)
    grounding: ChatGrounding
