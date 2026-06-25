"""End-to-end orchestration: profile → comparison → insight → safety (FR-022).

Single public entry point::

    result = run_pipeline(
        raw_profile_or_user_profile,
        analysis_date,
        generate_fn=my_llm_fn,      # optional; omit to skip insight generation
        dump_comparison="out.json", # optional; write comparison to disk
    )

    if result.success:
        print(result.insight_set)
    elif result.error:
        print("Pipeline failed:", result.error)

The deterministic layers (normalize → baselines → comparison → associations) always
run and are always inspectable via ``result.comparison``.  The LLM layer is optional
and isolated behind the ``generate_fn`` callable, which makes the pipeline fully
testable without a live API key.

Retry logic (``max_retries``):  on a SafetyError or a generation exception the
pipeline retries up to ``max_retries`` additional times before surfacing the error.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from .anomaly import detect_anomalies
from .comparison import build_comparison_object
from .config import MAX_INSIGHT_RETRIES
from .models import ComparisonObject, InsightSet, NudgeSet, UserProfile
from .normalize import normalize_profile
from .nudges import GenerateFn as _NudgeGenerateFn
from .nudges import generate_nudge_set
from .safety import SafetyError, check_insight_set


# ── Type alias ────────────────────────────────────────────────────────────────

GenerateFn = Callable[[ComparisonObject], InsightSet]


# ── Result container ──────────────────────────────────────────────────────────


@dataclass
class PipelineResult:
    """Output of a single pipeline run."""

    comparison: ComparisonObject
    insight_set: InsightSet | None = None
    error: str | None = None

    @property
    def success(self) -> bool:
        """True when an insight was produced and passed safety validation."""
        return self.insight_set is not None and self.error is None


# ── JSON dump helper ──────────────────────────────────────────────────────────


def _dump_comparison(comparison: ComparisonObject, path: str | Path) -> None:
    """Serialise *comparison* to JSON for debugging / inspection (FR-022)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        comparison.model_dump_json(indent=2),
        encoding="utf-8",
    )


# ── Default generate-fn loader ────────────────────────────────────────────────


def _load_default_generate_fn(model: str | None = None) -> GenerateFn | None:
    """Lazily import the real LLM generate function, bound to *model* if given."""
    try:
        from .llm.insight import generate_insights  # type: ignore[import]

        if model is None:
            return generate_insights
        return lambda comparison: generate_insights(comparison, model=model)
    except ImportError:
        return None


# ── Core pipeline ─────────────────────────────────────────────────────────────


def build_comparison(
    profile: UserProfile | dict,
    analysis_date: date | str | None = None,
) -> ComparisonObject:
    """Run only the deterministic layers and return the ComparisonObject.

    Useful for inspection, golden tests, and the dashboard's comparison view
    without triggering any LLM call.
    """
    if isinstance(profile, dict):
        profile = normalize_profile(profile)

    resolved_date: date
    if analysis_date is None:
        resolved_date = profile.records[-1].date
    elif isinstance(analysis_date, str):
        resolved_date = date.fromisoformat(analysis_date)
    else:
        resolved_date = analysis_date

    return build_comparison_object(profile.records, resolved_date)


def run_pipeline(
    profile: UserProfile | dict,
    analysis_date: date | str | None = None,
    *,
    generate_fn: GenerateFn | None = None,
    model: str | None = None,
    dump_comparison: str | Path | None = None,
    max_retries: int = MAX_INSIGHT_RETRIES,
) -> PipelineResult:
    """Run the full pipeline for one profile / date.

    Args:
        profile:         A ``UserProfile`` instance or a raw profile dict (which will
                         be normalized automatically).
        analysis_date:   The day to analyze.  Defaults to the last record date.
        generate_fn:     Callable ``(ComparisonObject) -> InsightSet``.  If *None*,
                         the pipeline attempts to import from ``llm.insight``; if that
                         package is also absent the pipeline returns a result with the
                         comparison object only and no insight.
        dump_comparison: If set, write the ComparisonObject to this path as JSON.
        max_retries:     Number of *additional* attempts after a SafetyError or
                         generation exception (default from config).

    Returns:
        A :class:`PipelineResult` whose ``comparison`` is always populated.
    """
    # ── Deterministic layers ──────────────────────────────────────────────────
    try:
        comparison = build_comparison(profile, analysis_date)
    except Exception as exc:  # pragma: no cover — guard against unexpected errors
        return PipelineResult(
            comparison=ComparisonObject(
                user_id="unknown",
                analysis_date=date.today(),
            ),
            error=f"Analysis failed: {exc}",
        )

    if dump_comparison is not None:
        _dump_comparison(comparison, dump_comparison)

    # ── LLM layer (optional) ──────────────────────────────────────────────────
    fn = generate_fn or _load_default_generate_fn(model=model)
    if fn is None:
        return PipelineResult(comparison=comparison)

    last_error: str | None = None
    for attempt in range(1 + max_retries):
        try:
            raw_insight_set = fn(comparison)
            validated = check_insight_set(raw_insight_set, comparison)
            return PipelineResult(comparison=comparison, insight_set=validated)
        except SafetyError as exc:
            last_error = f"Safety validation failed: {exc}"
        except Exception as exc:
            last_error = f"Insight generation error (attempt {attempt + 1}): {exc}"

    return PipelineResult(comparison=comparison, error=last_error)


# ── Phase 2: auto-nudge pipeline ─────────────────────────────────────────────


@dataclass
class NudgePipelineResult:
    """Output of a Phase 2 auto-nudge pipeline run (FR-001)."""

    comparison: ComparisonObject
    nudge_set: NudgeSet | None = None
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.nudge_set is not None and self.error is None


def run_nudge_pipeline(
    profile: UserProfile | dict,
    analysis_date: date | str | None = None,
    *,
    generate_fn: _NudgeGenerateFn | None = None,
    model: str | None = None,
    dump_comparison: str | Path | None = None,
    max_retries: int = MAX_INSIGHT_RETRIES,
) -> NudgePipelineResult:
    """Phase 2 pipeline: comparison → anomaly detection → NudgeSet (FR-001).

    Replaces the manual "generate insights" trigger.  A clean day (no anomalies)
    produces an empty ``NudgeSet`` without calling the LLM (FR-005).

    Args:
        profile:         A ``UserProfile`` or raw profile dict.
        analysis_date:   Day to analyse; defaults to last record date.
        generate_fn:     LLM callable ``(ComparisonObject) -> InsightSet``.  When
                         ``None``, the nudge/insight module is lazily imported; if
                         unavailable, ``nudge_set`` will be empty.
        model:           Model ID override (used when *generate_fn* is None).
        dump_comparison: Optional path to write the ``ComparisonObject`` as JSON.
        max_retries:     Additional attempts on ``SafetyError`` per nudge.

    Returns:
        A :class:`NudgePipelineResult` whose ``comparison`` is always populated.
    """
    try:
        comparison = build_comparison(profile, analysis_date)
    except Exception as exc:  # pragma: no cover
        return NudgePipelineResult(
            comparison=ComparisonObject(user_id="unknown", analysis_date=date.today()),
            error=f"Analysis failed: {exc}",
        )

    if dump_comparison is not None:
        _dump_comparison(comparison, dump_comparison)

    # Detect anomalies deterministically (no LLM involvement).
    anomalies = detect_anomalies(comparison)

    # Resolve generate_fn — may be None if no API key / package absent.
    fn = generate_fn or _load_default_generate_fn(model=model)

    try:
        nudge_set = generate_nudge_set(
            anomalies=anomalies,
            comparison=comparison,
            generate_fn=fn,
            max_retries=max_retries,
        )
        return NudgePipelineResult(comparison=comparison, nudge_set=nudge_set)
    except Exception as exc:  # pragma: no cover
        return NudgePipelineResult(comparison=comparison, error=f"Nudge generation failed: {exc}")
