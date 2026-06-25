"""Deterministic anomaly detection from a ComparisonObject (FR-002, FR-021).

Public API::

    anomalies = detect_anomalies(comparison)  # list[Anomaly], empty on a clean day

Rules are declarative and expressed as a table; every metric is checked against
the primary comparison window (monthly, falling back to weekly).  A metric that
is ``Stable / Within Normal Baseline`` (|Δ| < ANOMALY_MODERATE_PCT) raises no
anomaly.  The LLM is never involved in detection (Principle I, SC-006).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .config import (
    ANOMALY_MODERATE_PCT,
    ANOMALY_SIGNIFICANT_PCT,
    CRITICAL_THRESHOLD_PCT,
)
from .models import (
    Anomaly,
    AnomalyCode,
    AnomalySeverity,
    AnomalyTheme,
    ComparisonObject,
    MetricComparison,
)


# ── Severity mapping ──────────────────────────────────────────────────────────


def _severity(abs_pct: float | None) -> AnomalySeverity | None:
    """Map absolute percentage deviation to severity tier; None if sub-threshold."""
    if abs_pct is None:
        return None
    if abs_pct >= CRITICAL_THRESHOLD_PCT:
        return AnomalySeverity.critical
    if abs_pct >= ANOMALY_SIGNIFICANT_PCT:
        return AnomalySeverity.significant
    if abs_pct >= ANOMALY_MODERATE_PCT:
        return AnomalySeverity.moderate
    return None  # below threshold → no anomaly


def _primary_pct(mc: MetricComparison) -> float | None:
    """Return the primary window's percentage_change (monthly, else weekly)."""
    if mc.monthly.baseline_value is not None:
        return mc.monthly.percentage_change
    return mc.weekly.percentage_change


def _primary_tag(mc: MetricComparison) -> str:
    """Return the primary window's evaluation_tag (monthly, else weekly)."""
    if mc.monthly.baseline_value is not None:
        return mc.monthly.evaluation_tag
    return mc.weekly.evaluation_tag


# ── Anomaly rule definition ───────────────────────────────────────────────────


@dataclass(frozen=True)
class _Rule:
    code: AnomalyCode
    theme: AnomalyTheme
    section: str       # attribute name on ComparisonObject: "sleep", "heart_health", "activity"
    metric: str        # key in that section's dict
    elevated: bool     # True = fires when metric is above baseline; False = below


_RULES: tuple[_Rule, ...] = (
    _Rule(AnomalyCode.stress_elevated,    AnomalyTheme.stress,    "heart_health", "stress",         elevated=True),
    _Rule(AnomalyCode.hrv_depressed,      AnomalyTheme.recovery,  "heart_health", "hrv",            elevated=False),
    _Rule(AnomalyCode.steps_low,          AnomalyTheme.activity,  "activity",     "steps",          elevated=False),
    _Rule(AnomalyCode.active_minutes_low, AnomalyTheme.activity,  "activity",     "active_minutes", elevated=False),
    _Rule(AnomalyCode.sleep_insufficient, AnomalyTheme.sleep,     "sleep",        "sleep_duration", elevated=False),
    _Rule(AnomalyCode.sleep_quality_low,  AnomalyTheme.sleep,     "sleep",        "sleep_score",    elevated=False),
)


# ── Rule evaluation ───────────────────────────────────────────────────────────


def _evaluate_rule(rule: _Rule, comparison: ComparisonObject) -> Anomaly | None:
    """Evaluate one rule against *comparison*; return Anomaly or None."""
    section: dict[str, MetricComparison] = getattr(comparison, rule.section, {})
    mc = section.get(rule.metric)
    if mc is None:
        return None  # metric absent in this comparison object

    pct = _primary_pct(mc)
    if pct is None:
        return None  # no baseline available

    # Direction check: elevated rules fire when pct > 0; depressed rules when pct < 0.
    fires = pct > 0 if rule.elevated else pct < 0
    if not fires:
        return None

    sev = _severity(abs(pct))
    if sev is None:
        return None  # within the normal dead-band

    tag = _primary_tag(mc)
    direction = "above" if rule.elevated else "below"
    detail = f"{rule.metric} {abs(pct):.1f}% {direction} 30-day baseline"

    return Anomaly(
        code=rule.code,
        theme=rule.theme,
        severity=sev,
        signals=[rule.metric],
        evaluation_tag=tag,
        detail=detail,
    )


# ── Public API ────────────────────────────────────────────────────────────────


def detect_anomalies(comparison: ComparisonObject) -> list[Anomaly]:
    """Detect anomalies deterministically from *comparison*.

    Args:
        comparison: A fully-populated ``ComparisonObject`` from the analysis pipeline.

    Returns:
        Ordered list of :class:`Anomaly` instances — empty when the day is clean.
        Order follows ``_RULES`` declaration order (stress → hrv → steps → active_minutes
        → sleep_duration → sleep_score) for reproducibility (SC-006).
    """
    result: list[Anomaly] = []
    for rule in _RULES:
        anomaly = _evaluate_rule(rule, comparison)
        if anomaly is not None:
            result.append(anomaly)
    return result
