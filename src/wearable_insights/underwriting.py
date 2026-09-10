"""Deterministic underwriting signals (ClaimGuard integration, stage B).

Produces trend-based, explainable *soft context* for a human underwriter: activity
consistency, sleep regularity, cardiac stability, and data completeness — each with a
score, a direction, and the exact metric keys it was derived from.

Two rules govern this module, and both are structural rather than advisory:

1. **Every number here is computed in Python.**  The LLM (when enabled at all) only
   narrates values it cannot change — constitution Principle I.
2. **No decision, no price.**  Nothing in this module emits an approve/decline verdict
   or a premium impact.  It reports direction bands and the evidence behind them.

The scores are *stability* measures, not health judgements: they say how consistent a
person's own behaviour has been against their own history, which is why higher is always
better and why none of them reference a population norm.
"""

from __future__ import annotations

import statistics
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from .comparison import build_comparison_object
from .features import compute_features
from .models import CanonicalDailyRecord, ComparisonObject, UserProfile
from .normalize import normalize_profile

# Direction bands. Deliberately coarse — a 3-band label is defensible where a
# 2-decimal score implying precision would not be.
_FAVORABLE_MIN = 70
_ATTENTION_MAX = 45

# Coefficient-of-variation ceiling that maps to a score of 0.
_CV_CEILING = {"steps": 0.80, "resting_hr": 0.18, "hrv": 0.40, "sleep_duration": 0.30}

# Composite weights. Sum to 1.0; completeness is weighted lowest because it measures the
# evidence rather than the behaviour.
_COMPOSITE_WEIGHTS = {
    "activity_consistency": 0.35,
    "sleep_regularity": 0.35,
    "cardiac_stability": 0.30,
}

UNDERWRITING_DISCLAIMER: str = (
    "This is a decision-support signal derived from voluntarily shared wellness data. "
    "It is not a medical assessment, contains no diagnosis, and must not be the sole "
    "basis for an underwriting decision. All signals require human review."
)

SignalKey = Literal[
    "activity_consistency", "sleep_regularity", "cardiac_stability", "data_completeness"
]
Direction = Literal["favorable", "neutral", "attention"]


class UnderwritingSignal(BaseModel):
    """One explainable signal shown as a row in the underwriter's report."""

    key: SignalKey
    label: str
    score: int = Field(ge=0, le=100, description="Higher is always more stable/favorable.")
    direction: Direction
    metrics: list[str] = Field(
        default_factory=list, description="Provenance: exact ComparisonObject metric keys."
    )
    evaluation_tags: list[str] = Field(default_factory=list)
    days_with_data: int = 0
    detail: str = Field("", description="Deterministic template text — never LLM-authored.")


class UnderwritingComposite(BaseModel):
    """The three headline tiles. `volatility` is the only risk-polarity number."""

    consistency: int = Field(ge=0, le=100)
    completeness: int = Field(ge=0, le=100)
    volatility: int = Field(ge=0, le=100)


class UnderwritingSignalSet(BaseModel):
    user_id: str
    analysis_date: date
    window_days: int
    signals: list[UnderwritingSignal]
    composite: UnderwritingComposite
    data_coverage_pct: int = Field(ge=0, le=100)
    low_confidence: bool = False
    attention_points: list[str] = Field(default_factory=list)
    # Reserved for the flag-gated LLM narrative; always None in the deterministic build.
    narrative: str | None = None
    safety_profile: str | None = None
    disclaimer: str = UNDERWRITING_DISCLAIMER
    schema_version: str = "1.0"


# ── Scoring helpers ───────────────────────────────────────────────────────────


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _stability_from_cv(values: list[float], ceiling: float) -> tuple[int | None, float | None]:
    """Map a coefficient of variation onto 0-100, where 100 = perfectly steady."""
    usable = [v for v in values if v is not None]
    if len(usable) < 3:
        return None, None
    mean = statistics.mean(usable)
    if mean == 0:
        return None, None
    cv = statistics.stdev(usable) / abs(mean)
    return int(round(100 * (1.0 - _clamp01(cv / ceiling)))), cv


def _direction(score: int | None) -> Direction:
    if score is None:
        return "neutral"
    if score >= _FAVORABLE_MIN:
        return "favorable"
    if score <= _ATTENTION_MAX:
        return "attention"
    return "neutral"


def _series(records: list[CanonicalDailyRecord], attr: str) -> list[float]:
    return [
        float(getattr(r, attr))
        for r in records
        if getattr(r, attr, None) is not None
    ]


def _tags_for(comparison: ComparisonObject, section: str, metric: str) -> list[str]:
    """Collect the non-stable evaluation tags across the long windows for one metric."""
    mc = getattr(comparison, section, {}).get(metric)
    if mc is None:
        return []
    tags: list[str] = []
    for window in ("monthly", "sixty_day", "ninety_day"):
        wc = getattr(mc, window, None)
        if wc is not None and "Stable" not in wc.evaluation_tag:
            tags.append(f"{window}: {wc.evaluation_tag}")
    return tags


# ── Public API ────────────────────────────────────────────────────────────────


def build_underwriting_signals(
    profile: UserProfile | dict[str, Any],
    analysis_date: date | None = None,
    *,
    window_days: int = 90,
) -> UnderwritingSignalSet:
    """Compute the deterministic underwriting signal set for one applicant.

    Args:
        profile:      A ``UserProfile`` or a raw profile dict (normalized automatically).
        analysis_date: Day to assess; defaults to the last record date.
        window_days:  Trailing window the stability measures are computed over.
    """
    if isinstance(profile, dict):
        profile = normalize_profile(profile)

    resolved = analysis_date or profile.records[-1].date
    ordered = sorted(profile.records, key=lambda r: r.date)
    window = [r for r in ordered if r.date <= resolved][-window_days:]
    comparison = build_comparison_object(ordered, resolved)

    signals: list[UnderwritingSignal] = []
    attention: list[str] = []

    # ── Activity consistency: step-count steadiness + hitting one's own median ──
    steps = _series(window, "steps")
    step_score, step_cv = _stability_from_cv(steps, _CV_CEILING["steps"])
    if step_score is not None and steps:
        median = statistics.median(steps)
        hit_rate = sum(1 for v in steps if v >= 0.9 * median) / len(steps)
        # Blend steadiness with adherence so a consistently sedentary person does not
        # score as "favorable" purely for being consistent.
        blended = int(round(0.6 * step_score + 40 * hit_rate))
        signals.append(
            UnderwritingSignal(
                key="activity_consistency",
                label="Activity consistency",
                score=min(100, blended),
                direction=_direction(min(100, blended)),
                metrics=["activity.steps", "activity.active_minutes"],
                evaluation_tags=_tags_for(comparison, "activity", "steps"),
                days_with_data=len(steps),
                detail=(
                    f"Step count varied {step_cv:.0%} around a {int(median):,}-step median "
                    f"across {len(steps)} days with data; {hit_rate:.0%} of days reached "
                    "90% of that median."
                ),
            )
        )

    # ── Sleep regularity: bedtime stability (reuses features.py) + duration steadiness ──
    consistency_scores = [
        f for r in window
        if (f := compute_features(ordered, r.date).sleep_consistency_score) is not None
    ]
    dur_score, dur_cv = _stability_from_cv(
        _series(window, "sleep_duration_minutes"), _CV_CEILING["sleep_duration"]
    )
    if consistency_scores or dur_score is not None:
        bedtime_component = (
            int(round(100 * statistics.mean(consistency_scores))) if consistency_scores else None
        )
        parts = [p for p in (bedtime_component, dur_score) if p is not None]
        score = int(round(statistics.mean(parts)))
        detail_bits = []
        if bedtime_component is not None:
            detail_bits.append(f"bedtime stability {bedtime_component}/100")
        if dur_cv is not None:
            detail_bits.append(f"sleep duration varied {dur_cv:.0%}")
        signals.append(
            UnderwritingSignal(
                key="sleep_regularity",
                label="Sleep regularity",
                score=score,
                direction=_direction(score),
                metrics=["sleep.sleep_duration", "sleep.sleep_score"],
                evaluation_tags=_tags_for(comparison, "sleep", "sleep_duration"),
                days_with_data=len(_series(window, "sleep_duration_minutes")),
                detail="; ".join(detail_bits) + "." if detail_bits else "",
            )
        )

    # ── Cardiac stability: resting-HR and HRV steadiness, plus long-window drift ──
    hr_score, hr_cv = _stability_from_cv(_series(window, "resting_hr"), _CV_CEILING["resting_hr"])
    hrv_score, hrv_cv = _stability_from_cv(_series(window, "hrv_rmssd_ms"), _CV_CEILING["hrv"])
    cardiac_parts = [p for p in (hr_score, hrv_score) if p is not None]
    if cardiac_parts:
        score = int(round(statistics.mean(cardiac_parts)))
        tags = _tags_for(comparison, "heart_health", "resting_hr") + _tags_for(
            comparison, "heart_health", "hrv"
        )
        bits = []
        if hr_cv is not None:
            bits.append(f"resting HR varied {hr_cv:.0%}")
        if hrv_cv is not None:
            bits.append(f"HRV varied {hrv_cv:.0%}")
        signals.append(
            UnderwritingSignal(
                key="cardiac_stability",
                label="Resting HR / HRV stability",
                score=score,
                direction=_direction(score),
                metrics=["heart_health.resting_hr", "heart_health.hrv"],
                evaluation_tags=tags,
                days_with_data=len(_series(window, "resting_hr")),
                detail="; ".join(bits) + f" over {len(window)} days." if bits else "",
            )
        )

    # ── Data completeness: how much evidence actually exists ──────────────────
    tracked_attrs = (
        "sleep_duration_minutes", "sleep_score", "deep_sleep_minutes", "rem_sleep_minutes",
        "resting_hr", "hrv_rmssd_ms", "stress_score", "steps", "active_minutes",
    )
    expected = len(window) * len(tracked_attrs)
    present = sum(
        1 for r in window for a in tracked_attrs if getattr(r, a, None) is not None
    )
    coverage = int(round(100 * present / expected)) if expected else 0
    # A short history caps completeness: 22 days of perfect data is not 100% evidence.
    horizon_factor = _clamp01(len(window) / min(window_days, 60))
    completeness = int(round(coverage * horizon_factor))
    signals.append(
        UnderwritingSignal(
            key="data_completeness",
            label="Data completeness",
            score=completeness,
            direction=_direction(completeness),
            metrics=["data_quality.missing_fields", "data_quality.low_confidence"],
            evaluation_tags=(
                ["low_confidence: under 30 days of history"] if len(window) < 30 else []
            ),
            days_with_data=len(window),
            detail=(
                f"{present:,} of {expected:,} expected metric-days present ({coverage}%) "
                f"across {len(window)} days of history."
            ),
        )
    )

    # ── Composite tiles ───────────────────────────────────────────────────────
    by_key = {s.key: s for s in signals}
    weighted, weight_total = 0.0, 0.0
    for key, weight in _COMPOSITE_WEIGHTS.items():
        sig = by_key.get(key)
        if sig is not None:
            weighted += sig.score * weight
            weight_total += weight
    consistency = int(round(weighted / weight_total)) if weight_total else 0

    composite = UnderwritingComposite(
        consistency=consistency,
        completeness=completeness,
        # Volatility is the inverse of behavioural consistency — the one risk-polarity
        # tile, so the UI can colour it in the opposite direction.
        volatility=100 - consistency,
    )

    for sig in signals:
        if sig.direction == "attention":
            attention.append(f"{sig.label} is low ({sig.score}/100) — {sig.detail}")
    if len(window) < 30:
        attention.append(
            f"Only {len(window)} days of history available; signals below 30 days should be "
            "treated as provisional."
        )

    return UnderwritingSignalSet(
        user_id=profile.user_id if hasattr(profile, "user_id") else comparison.user_id,
        analysis_date=resolved,
        window_days=window_days,
        signals=signals,
        composite=composite,
        data_coverage_pct=coverage,
        low_confidence=comparison.data_quality.low_confidence or len(window) < 30,
        attention_points=attention,
    )
