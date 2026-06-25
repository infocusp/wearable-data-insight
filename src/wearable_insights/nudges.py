"""Nudge consolidation: Anomaly[] → bounded NudgeSet (FR-001, FR-003–FR-007).

Public API::

    nudge_set = generate_nudge_set(anomalies, comparison, generate_fn=my_llm_fn)

Pipeline:
1. Group anomalies by theme (sleep / recovery / activity / stress).
2. Sort groups by max severity (critical > significant > moderate).
3. Take the top MAX_NUDGES_PER_DAY groups.
4. For each group, generate a per-nudge ``Insight`` by calling *generate_fn*
   with a theme-focused view of the comparison object (D3).
5. Gate each insight through ``safety.check_insight_set`` (FR-017, T017).
6. Assemble ``Nudge`` + ``NudgeSet``.

A clean day (no anomalies) produces an empty ``NudgeSet`` without calling the LLM
(FR-005).  *generate_fn* defaults to ``llm.insight.generate_insights`` when
``None`` is passed.
"""

from __future__ import annotations

from datetime import date
from typing import Callable

from .config import DISCLAIMER, MAX_INSIGHT_RETRIES, MAX_NUDGES_PER_DAY
from .models import (
    Anomaly,
    AnomalySeverity,
    AnomalyTheme,
    ComparisonObject,
    Insight,
    InsightSet,
    Nudge,
    NudgeSet,
    _SEVERITY_ORDER,
)
from .safety import SafetyError, check_insight_set

GenerateFn = Callable[[ComparisonObject], InsightSet]

# ── Focused comparison helper ─────────────────────────────────────────────────


def _focused_comparison(
    comparison: ComparisonObject,
    theme: AnomalyTheme,
    signals: set[str],
) -> ComparisonObject:
    """Return a subset of *comparison* scoped to the given theme's signals.

    Only the sections and metrics that belong to the triggering signals are
    included.  The LLM is then grounded in just this theme's data (D3).
    """
    def _filter(section: dict) -> dict:
        return {k: v for k, v in section.items() if k in signals}

    # Sleep theme: pass the entire sleep section — sleep metric keys (sleep_score,
    # sleep_duration, …) never match live-signal names (hrv, hr, …), so per-signal
    # filtering would always produce an empty dict and lose all sleep context.
    sleep = comparison.sleep if theme == AnomalyTheme.sleep else {}
    heart_health = (
        _filter(comparison.heart_health)
        # vitals (SpO₂/skin-temp/respiration) are synthesized under heart_health too
        # for the live-nudge path (Feature 003), so they ground here as well.
        if theme in (AnomalyTheme.recovery, AnomalyTheme.stress, AnomalyTheme.vitals)
        else {}
    )
    activity = _filter(comparison.activity) if theme == AnomalyTheme.activity else {}

    # Keep associations that reference any of the anomaly signals.
    assocs = [
        a for a in comparison.candidate_associations
        if set(a.signals) & signals
    ]

    return comparison.model_copy(update={
        "sleep": sleep,
        "heart_health": heart_health,
        "activity": activity,
        "candidate_associations": assocs,
    })


# ── Nudge ID builder ──────────────────────────────────────────────────────────


def _nudge_id(user_id: str, analysis_date: date, theme: AnomalyTheme) -> str:
    return f"{user_id}_{analysis_date.isoformat()}_{theme.value}"


# ── Max severity helper ───────────────────────────────────────────────────────


def _max_severity(anomalies: list[Anomaly]) -> AnomalySeverity:
    return max(anomalies, key=lambda a: _SEVERITY_ORDER[a.severity]).severity


# ── LLM loader ───────────────────────────────────────────────────────────────


def _load_default_generate_fn() -> GenerateFn | None:
    try:
        from .llm.insight import generate_insights  # type: ignore[import]
        return generate_insights
    except ImportError:
        return None


# ── Per-nudge insight generation with safety gate (T015, T017) ───────────────


def _generate_nudge_insight(
    focused: ComparisonObject,
    generate_fn: GenerateFn,
    max_retries: int,
) -> Insight | None:
    """Generate and safety-gate a single Insight for one theme's focused comparison.

    Returns ``None`` if all retries fail (nudge is silently skipped).
    """
    last_exc: Exception | None = None
    for attempt in range(1 + max_retries):
        try:
            raw_set = generate_fn(focused)
            validated = check_insight_set(raw_set, focused)
            if validated.insights:
                return validated.insights[0]
        except SafetyError as exc:
            last_exc = exc
        except Exception as exc:
            last_exc = exc
    return None


# ── Group consolidation (T014) ────────────────────────────────────────────────


def consolidate_nudge_groups(
    anomalies: list[Anomaly],
) -> list[tuple[AnomalyTheme, list[Anomaly]]]:
    """Group anomalies by theme, ordered by descending max severity.

    Returns:
        List of (theme, [anomalies]) tuples, most severe theme first.
    """
    groups: dict[AnomalyTheme, list[Anomaly]] = {}
    for a in anomalies:
        groups.setdefault(a.theme, []).append(a)

    return sorted(
        groups.items(),
        key=lambda kv: _SEVERITY_ORDER[_max_severity(kv[1])],
        reverse=True,
    )


# ── Public API ────────────────────────────────────────────────────────────────


def generate_nudge_set(
    anomalies: list[Anomaly],
    comparison: ComparisonObject,
    generate_fn: GenerateFn | None = None,
    max_retries: int = MAX_INSIGHT_RETRIES,
) -> NudgeSet:
    """Build a bounded ``NudgeSet`` from *anomalies*.

    Args:
        anomalies:    Detected anomalies for the day (from ``anomaly.detect_anomalies``).
        comparison:   The full ``ComparisonObject`` for grounding.
        generate_fn:  LLM callable ``(ComparisonObject) -> InsightSet``; defaults to
                      ``llm.insight.generate_insights``.  Pass a stub in tests to avoid
                      a live API key.
        max_retries:  Additional retry attempts on ``SafetyError`` (default from config).

    Returns:
        A ``NudgeSet`` with 0 .. MAX_NUDGES_PER_DAY nudges.  Empty on a clean day.
    """
    if not anomalies:
        return NudgeSet(
            user_id=comparison.user_id,
            analysis_date=comparison.analysis_date,
            nudges=[],
        )

    fn = generate_fn or _load_default_generate_fn()

    groups = consolidate_nudge_groups(anomalies)
    nudges: list[Nudge] = []

    for theme, theme_anomalies in groups[:MAX_NUDGES_PER_DAY]:
        signals = set(s for a in theme_anomalies for s in a.signals)
        focused = _focused_comparison(comparison, theme, signals)

        if fn is None:
            break

        insight = _generate_nudge_insight(focused, fn, max_retries)
        if insight is None:
            continue  # safety gate failed all retries; skip this nudge silently

        nudges.append(
            Nudge(
                nudge_id=_nudge_id(comparison.user_id, comparison.analysis_date, theme),
                user_id=comparison.user_id,
                analysis_date=comparison.analysis_date,
                theme=theme,
                severity=_max_severity(theme_anomalies),
                anomalies=theme_anomalies,
                insight=insight,
                disclaimer=DISCLAIMER,
                triggered_by=sorted(signals),
            )
        )

    return NudgeSet(
        user_id=comparison.user_id,
        analysis_date=comparison.analysis_date,
        nudges=nudges,
    )
