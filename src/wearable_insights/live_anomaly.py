"""Deterministic live-anomaly detection over the rolling intraday buffer (Feature 003/004).

This reverses the Phase-2 "live vitals are presentation-only" stance: the rolling buffer
produced by ``data/live.py`` now drives anomaly detection.  Detection stays pure, seeded
Python — the LLM only interprets a *synthesized* ``ComparisonObject`` (constitution
Principle I); it never sees raw samples or computes deviations.

Feature 004 extends the anchor source: instead of a flat per-day resting anchor, the
detector now looks up a time-of-day slotted baseline — the historical average for the
*current* 3-hour slot and day-type (weekday/weekend) over 7-day and 30-day horizons.
The flat-dict path is retained for backward compatibility with existing tests.

Public API::

    anomalies = detect_live_anomalies(buffer, baselines, mode, ...)  # list[Anomaly]
    comparison = synthesize_comparison(anomalies, buffer, baselines,  # ComparisonObject
                                       user_id, analysis_date, ...)
    new, state = filter_new_anomalies(anomalies, state, now)          # de-dup + cooldown

``baselines`` may be a ``SlottedBaselineSet`` (slotted path, Feature 004) or a plain
``dict[str, float]`` (legacy flat path, Feature 003).  Pass ``current_minute`` and
``current_day_type`` when using the slotted path.

A sustained deviation is judged from the **mean of the last ``LIVE_ANOMALY_WINDOW``
samples** vs the anchor.  Averaging suppresses single-sample sensor noise so a transient
spike raises no anomaly (FR-005).  Severity reuses the existing percentage tiers; the
synthesized comparison reuses ``trends.percentage_change`` so the value space matches the
daily pipeline exactly.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from .config import LIVE_ANOMALY_MIN_SAMPLES, LIVE_ANOMALY_WINDOW, NUDGE_COOLDOWN_SECS
from .data.slotted_baselines import (
    SlottedBaselineSet,
    day_type as _day_type,
    lookup_anchor,
    slot_index,
    slot_label,
)
from .models import (
    Anomaly,
    AnomalyCode,
    AnomalySeverity,
    AnomalyTheme,
    ComparisonObject,
    MetricComparison,
    WindowComparison,
)
from .trends import percentage_change

# Per-signal percentage dead-bands (moderate, significant, critical) measured against the
# person's *own* baseline — associative, not clinical cutoffs (constitution Principle II).
# Calibrated to each signal's physiological variability: HR/HRV swing widely, SpO₂ barely.
_SIGNAL_THRESHOLDS: dict[str, tuple[float, float, float]] = {
    "hr":        (15.0, 30.0, 50.0),
    "hrv":       (15.0, 30.0, 50.0),
    "resp_rate": (12.0, 20.0, 30.0),
    "spo2":      (1.5, 3.0, 5.0),
    "skin_temp": (1.0, 2.0, 3.0),
}


def _signal_severity(signal: str, abs_pct: float) -> AnomalySeverity | None:
    """Map an absolute % deviation to a severity tier using the signal's own dead-bands."""
    moderate, significant, critical = _SIGNAL_THRESHOLDS[signal]
    if abs_pct >= critical:
        return AnomalySeverity.critical
    if abs_pct >= significant:
        return AnomalySeverity.significant
    if abs_pct >= moderate:
        return AnomalySeverity.moderate
    return None  # within dead-band → no anomaly


def _eval_tag(severity: AnomalySeverity, elevated: bool) -> str:
    """Deterministic WindowComparison.evaluation_tag from severity + direction."""
    if severity is AnomalySeverity.critical:
        return "Critically Elevated" if elevated else "Critically Depressed"
    return "Significantly Elevated" if elevated else "Significantly Depressed"


# ── Per-signal rule table ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class _LiveRule:
    signal: str        # buffer key: hr / hrv / spo2 / skin_temp / resp_rate
    elevated: bool     # True = concerning when *above* anchor; False = when below
    code: AnomalyCode
    theme: AnomalyTheme


# Declaration order defines the reproducible anomaly ordering (SC-003 / constitution VI).
_RULES: tuple[_LiveRule, ...] = (
    _LiveRule("hr",        True,  AnomalyCode.hr_elevated,        AnomalyTheme.stress),
    _LiveRule("hrv",       False, AnomalyCode.hrv_depressed,      AnomalyTheme.recovery),
    _LiveRule("spo2",      False, AnomalyCode.spo2_low,           AnomalyTheme.vitals),
    _LiveRule("skin_temp", True,  AnomalyCode.skin_temp_elevated, AnomalyTheme.vitals),
    _LiveRule("resp_rate", True,  AnomalyCode.resp_rate_elevated, AnomalyTheme.vitals),
)

_SIGNAL_LABEL = {
    "hr": "heart rate",
    "hrv": "HRV",
    "spo2": "SpO₂",
    "skin_temp": "skin temperature",
    "resp_rate": "respiration rate",
}


# ── Windowed mean (the low-pass filter that defines "sustained") ───────────────


def _windowed_mean(
    buffer: Sequence[dict[str, Any]],
    key: str,
    window: int,
    min_samples: int,
) -> float | None:
    """Mean of the last *window* samples for *key*; None if too few present."""
    recent = list(buffer)[-window:]
    vals = [s[key] for s in recent if s.get(key) is not None]
    if len(vals) < min_samples:
        return None
    return sum(vals) / len(vals)


# ── Anchor resolution (slotted or flat) ───────────────────────────────────────


def _resolve_anchor(
    baselines: SlottedBaselineSet | dict[str, float],
    signal: str,
    slot: int,
    dt: str,
    horizon: int,
) -> float | None:
    """Return the anchor for *signal* from either a slotted or flat baseline source."""
    if isinstance(baselines, SlottedBaselineSet):
        return lookup_anchor(baselines, signal, slot, dt, horizon)
    # Legacy flat-dict path — horizon ignored, all windows get the same anchor.
    return baselines.get(signal)


# ── Detection result (internal) ───────────────────────────────────────────────


@dataclass(frozen=True)
class _Detection:
    rule: _LiveRule
    mean: float
    anchor: float
    pct: float
    slot: int
    dt: str


def _evaluate(
    buffer: Sequence[dict[str, Any]],
    baselines: SlottedBaselineSet | dict[str, float],
    *,
    slot: int,
    dt: str,
    primary_horizon: int,
    window: int,
    min_samples: int,
) -> list[_Detection]:
    """Evaluate every rule against the buffer window; return firing detections in order."""
    detections: list[_Detection] = []
    for rule in _RULES:
        anchor = _resolve_anchor(baselines, rule.signal, slot, dt, primary_horizon)
        if not anchor:  # missing or zero anchor → cannot compute a deviation
            continue
        mean = _windowed_mean(buffer, rule.signal, window, min_samples)
        if mean is None:
            continue
        pct = percentage_change(mean, anchor)
        if pct is None:
            continue
        fires = pct > 0 if rule.elevated else pct < 0
        if not fires:
            continue
        if _signal_severity(rule.signal, abs(pct)) is None:
            continue
        detections.append(_Detection(rule=rule, mean=mean, anchor=anchor, pct=pct, slot=slot, dt=dt))
    return detections


def _to_anomaly(det: _Detection) -> Anomaly:
    sev = _signal_severity(det.rule.signal, abs(det.pct))
    assert sev is not None
    direction = "above" if det.rule.elevated else "below"
    label = _SIGNAL_LABEL.get(det.rule.signal, det.rule.signal)
    time_context = f"{slot_label(det.slot)}, {det.dt}"
    detail = (
        f"{label} {abs(det.pct):.1f}% {direction} the expected level "
        f"for this time of day ({time_context})"
    )
    return Anomaly(
        code=det.rule.code,
        theme=det.rule.theme,
        severity=sev,
        signals=[det.rule.signal],
        evaluation_tag=_eval_tag(sev, det.rule.elevated),
        detail=detail,
    )


# ── Public: detection ─────────────────────────────────────────────────────────


def _remap_for_wake_up(anomaly: Anomaly) -> Anomaly:
    """Re-classify an HRV-depressed anomaly as sleep-quality when waking up.

    In wake-up mode a suppressed HRV directly reflects overnight recovery quality, so we
    surface it as a *sleep* theme nudge (sleep_quality_low) rather than a generic
    recovery nudge. All other anomalies pass through unchanged.
    """
    if anomaly.code is not AnomalyCode.hrv_depressed:
        return anomaly
    return Anomaly(
        code=AnomalyCode.sleep_quality_low,
        theme=AnomalyTheme.sleep,
        severity=anomaly.severity,
        signals=anomaly.signals,
        evaluation_tag=anomaly.evaluation_tag,
        detail=anomaly.detail.replace(
            "HRV", "HRV (overnight recovery indicator)"
        ) + " — may reflect poor sleep quality from last night",
    )


def detect_live_anomalies(
    buffer: Sequence[dict[str, Any]],
    baselines: SlottedBaselineSet | dict[str, float],
    mode: str = "resting",
    *,
    current_minute: int = 8 * 60,   # default: 08:00 (session start)
    current_day_type: str = "weekday",
    window: int = LIVE_ANOMALY_WINDOW,
    min_samples: int = LIVE_ANOMALY_MIN_SAMPLES,
    primary_horizon: int = 30,
) -> list[Anomaly]:
    """Detect sustained live anomalies from *buffer* vs *baselines*.

    Args:
        buffer:            Rolling list of live samples (each a dict with signal keys).
        baselines:         Either a ``SlottedBaselineSet`` (time-of-day slotted, Feature
                           004) or a flat ``dict[str, float]`` (legacy flat anchor).
        mode:              Current activity context (kept for provenance/telemetry).
        current_minute:    Device minute-of-day used to pick the current slot (slotted
                           path only; ignored for flat dict).
        current_day_type:  "weekday" or "weekend" (slotted path only).
        window:            Trailing samples to average.
        min_samples:       Minimum present samples required to evaluate a signal.
        primary_horizon:   Which horizon (days) drives the firing decision when using
                           slotted baselines.  Defaults to 30 (monthly).

    Returns:
        Ordered ``Anomaly`` list (rule-declaration order), empty when nothing fires.
    """
    slot = slot_index(current_minute)
    anomalies = [
        _to_anomaly(d)
        for d in _evaluate(
            buffer,
            baselines,
            slot=slot,
            dt=current_day_type,
            primary_horizon=primary_horizon,
            window=window,
            min_samples=min_samples,
        )
    ]
    if mode == "wake-up":
        anomalies = [_remap_for_wake_up(a) for a in anomalies]
    return anomalies


# ── Public: synthesized comparison object (LLM grounding) ─────────────────────


def synthesize_comparison(
    anomalies: Sequence[Anomaly],
    buffer: Sequence[dict[str, Any]],
    baselines: SlottedBaselineSet | dict[str, float],
    user_id: str,
    analysis_date: date,
    *,
    current_minute: int = 8 * 60,
    current_day_type: str = "weekday",
    window: int = LIVE_ANOMALY_WINDOW,
    min_samples: int = LIVE_ANOMALY_MIN_SAMPLES,
) -> ComparisonObject:
    """Build a comparison-shaped grounding object for the live anomalies.

    For the slotted path (``SlottedBaselineSet``), each triggering signal gets both a
    7-day (``weekly``) and 30-day (``monthly``) window populated from the matching
    (slot, day_type) bucket, so the LLM and nudge generator see horizon-aware context.

    For the legacy flat-dict path, behaviour is unchanged: a single anchor populates the
    ``monthly`` window only (matching Feature 003 behaviour).
    """
    slot = slot_index(current_minute)
    heart_health: dict[str, MetricComparison] = {}

    for anomaly in anomalies:
        signal = anomaly.signals[0]
        mean = _windowed_mean(buffer, signal, window, min_samples)
        if mean is None:
            continue

        if isinstance(baselines, SlottedBaselineSet):
            mc = _build_slotted_metric(baselines, signal, mean, slot, current_day_type, anomaly)
        else:
            anchor = baselines.get(signal)
            if anchor is None:
                continue
            mc = _build_flat_metric(mean, anchor, anomaly)

        heart_health[signal] = mc

    return ComparisonObject(
        user_id=user_id,
        analysis_date=analysis_date,
        heart_health=heart_health,
    )


def _build_slotted_metric(
    baselines: SlottedBaselineSet,
    signal: str,
    mean: float,
    slot: int,
    dt: str,
    anomaly: Anomaly,
) -> MetricComparison:
    """Build MetricComparison with weekly (7d) and monthly (30d) windows from buckets."""
    windows: dict[str, WindowComparison] = {}
    for horizon, field_name in ((7, "weekly"), (30, "monthly")):
        if horizon not in baselines.horizons:
            continue
        anchor = lookup_anchor(baselines, signal, slot, dt, horizon)
        if anchor is None:
            continue
        pct = percentage_change(mean, anchor) or 0.0
        rule = next((r for r in _RULES if r.signal == signal), None)
        elevated = pct > 0
        sev = _signal_severity(signal, abs(pct))
        if sev is not None and rule is not None:
            tag = _eval_tag(sev, elevated if rule.elevated else not elevated)
        else:
            tag = "Stable / Within Normal Baseline"
        windows[field_name] = WindowComparison(
            baseline_value=round(anchor, 2),
            percentage_change=pct,
            trend="up" if pct > 0 else "down" if pct < 0 else "stable",
            evaluation_tag=tag,
        )

    # Fill the primary anomaly window with the anomaly's own tag for LLM consistency.
    primary_window = windows.get("monthly") or windows.get("weekly")
    if primary_window is not None:
        primary_window = WindowComparison(
            baseline_value=primary_window.baseline_value,
            percentage_change=primary_window.percentage_change,
            trend=primary_window.trend,
            evaluation_tag=anomaly.evaluation_tag,
        )
        windows["monthly"] = primary_window

    return MetricComparison(
        current_value=round(mean, 2),
        weekly=windows.get("weekly", WindowComparison()),
        monthly=windows.get("monthly", WindowComparison()),
    )


def _build_flat_metric(mean: float, anchor: float, anomaly: Anomaly) -> MetricComparison:
    """Legacy flat-anchor metric: single anchor → monthly window only."""
    pct = percentage_change(mean, anchor) or 0.0
    return MetricComparison(
        current_value=round(mean, 2),
        monthly=WindowComparison(
            baseline_value=round(anchor, 2),
            percentage_change=pct,
            trend="up" if pct > 0 else "down" if pct < 0 else "stable",
            evaluation_tag=anomaly.evaluation_tag,
        ),
    )


# ── Public: de-duplication + cooldown (FR-010, FR-016) ────────────────────────


def filter_new_anomalies(
    detections: Iterable[Anomaly],
    state: dict[str, dict[str, Any]],
    now: float,
    *,
    cooldown: float = NUDGE_COOLDOWN_SECS,
) -> tuple[list[Anomaly], dict[str, dict[str, Any]]]:
    """Return only anomalies that should raise a *new* nudge, and the updated *state*.

    Episode model (data-model §5), keyed by ``AnomalyCode.value``:
      * a code present this sync but not currently ``active`` → new episode; eligible to
        raise iff it has never raised or its cooldown has elapsed since ``last_raised_ts``;
      * a code already ``active`` → suppressed (already raised this episode);
      * a code absent this sync → episode ends (``active=False``), may re-raise later.

    ``state`` is mutated in place and also returned for convenience.
    """
    detected = {a.code.value for a in detections}

    for code, entry in state.items():
        if code not in detected:
            entry["active"] = False

    new: list[Anomaly] = []
    for anomaly in detections:
        code = anomaly.code.value
        entry = state.setdefault(code, {"active": False, "last_raised_ts": None})
        if entry["active"]:
            continue
        last = entry["last_raised_ts"]
        if last is None or (now - last) >= cooldown:
            entry["active"] = True
            entry["last_raised_ts"] = now
            new.append(anomaly)
    return new, state
