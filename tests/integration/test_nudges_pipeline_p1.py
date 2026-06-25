"""Integration test: snapshot → comparison → anomalies → NudgeSet (T012, SC-001).

End-to-end auto-nudge pipeline using a stubbed LLM — no ANTHROPIC_API_KEY needed.
"""

from __future__ import annotations

from datetime import date

import pytest

from wearable_insights.config import DISCLAIMER, MAX_NUDGES_PER_DAY
from wearable_insights.data.synthetic import build_recovery_deficit_snapshot, generate_synthetic_profile
from wearable_insights.models import ComparisonObject, Insight, InsightSet, NudgeSet
from wearable_insights.normalize import normalize_profile
from wearable_insights.pipeline import NudgePipelineResult, run_nudge_pipeline


# ── Stub generate function ────────────────────────────────────────────────────

def _stub_generate(comparison: ComparisonObject) -> InsightSet:
    sig = next(
        iter(comparison.heart_health or comparison.sleep or comparison.activity),
        "stress",
    )
    return InsightSet(
        insights=[
            Insight(
                title="Stub insight",
                summary="Your metrics may be associated with recent patterns.",
                action="Take a 10-minute walk this evening.",
                confidence="high",
                source_signals=[sig],
            )
        ],
        disclaimer=DISCLAIMER,
        generated_from=[sig],
    )


# ── SC-001: recovery-deficit day raises nudges automatically ─────────────────

def test_recovery_deficit_raises_at_least_one_nudge():
    """SC-001: auto-nudge pipeline raises ≥1 nudge for the recovery-deficit day."""
    raw = build_recovery_deficit_snapshot(seed=42, days=31)
    result = run_nudge_pipeline(raw, generate_fn=_stub_generate)
    assert isinstance(result, NudgePipelineResult)
    assert result.success
    assert result.nudge_set is not None
    assert len(result.nudge_set.nudges) >= 1


def test_recovery_deficit_nudge_set_is_valid():
    raw = build_recovery_deficit_snapshot(seed=42, days=31)
    result = run_nudge_pipeline(raw, generate_fn=_stub_generate)
    ns = result.nudge_set
    assert ns.user_id == "usr_recovery_deficit"
    assert isinstance(ns.analysis_date, date)
    assert ns.schema_version == "1.0"


def test_recovery_deficit_nudge_has_required_fields():
    raw = build_recovery_deficit_snapshot(seed=42, days=31)
    result = run_nudge_pipeline(raw, generate_fn=_stub_generate)
    for nudge in result.nudge_set.nudges:
        assert nudge.nudge_id
        assert nudge.insight.title
        assert nudge.insight.action
        assert nudge.insight.confidence in ("low", "medium", "high")
        assert nudge.disclaimer
        assert len(nudge.anomalies) >= 1
        assert len(nudge.triggered_by) >= 1


# ── SC-002: clean day raises zero nudges ─────────────────────────────────────

def test_clean_day_raises_no_nudges():
    """SC-002: healthy_consistent day produces an empty NudgeSet."""
    raw = generate_synthetic_profile("healthy_consistent", seed=42, days=31)
    result = run_nudge_pipeline(raw, generate_fn=_stub_generate)
    assert result.success
    assert result.nudge_set is not None
    assert result.nudge_set.nudges == []


# ── SC-008: nudge cap ─────────────────────────────────────────────────────────

def test_nudge_count_is_bounded():
    """SC-008: never more than MAX_NUDGES_PER_DAY nudges."""
    raw = build_recovery_deficit_snapshot(seed=42, days=31)
    result = run_nudge_pipeline(raw, generate_fn=_stub_generate)
    assert len(result.nudge_set.nudges) <= MAX_NUDGES_PER_DAY


# ── Comparison is always populated ───────────────────────────────────────────

def test_comparison_always_in_result():
    raw = build_recovery_deficit_snapshot(seed=42, days=31)
    result = run_nudge_pipeline(raw, generate_fn=_stub_generate)
    assert result.comparison is not None
    assert result.comparison.user_id == "usr_recovery_deficit"


def test_run_nudge_pipeline_without_generate_fn_returns_empty_nudges():
    """Without a generate_fn, nudges cannot be created → empty NudgeSet."""
    raw = build_recovery_deficit_snapshot(seed=42, days=31)
    result = run_nudge_pipeline(raw, generate_fn=None)
    assert result.comparison is not None
    # With no generate_fn, anomalies detected but no insights generated
    assert result.nudge_set is not None
    assert result.nudge_set.nudges == []


# ── Safety gate on nudge insights ────────────────────────────────────────────

def test_unsafe_insight_is_not_surfaced():
    """T017: An insight that fails the safety gate is retried, not surfaced raw."""
    call_count = 0

    def _bad_then_good(comparison: ComparisonObject) -> InsightSet:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return InsightSet(
                insights=[
                    Insight(
                        title="Bad",
                        summary="This disease causes your fatigue.",
                        action="Diagnose yourself.",
                        confidence="low",
                        source_signals=["stress"],
                    )
                ],
                disclaimer=DISCLAIMER,
                generated_from=["stress"],
            )
        return InsightSet(
            insights=[
                Insight(
                    title="Safe",
                    summary="Your stress may be associated with recovery patterns.",
                    action="Take a short walk.",
                    confidence="high",
                    source_signals=["stress"],
                )
            ],
            disclaimer=DISCLAIMER,
            generated_from=["stress"],
        )

    raw = build_recovery_deficit_snapshot(seed=42, days=31)
    result = run_nudge_pipeline(raw, generate_fn=_bad_then_good, max_retries=2)
    # Eventually a safe insight should be produced
    if result.nudge_set and result.nudge_set.nudges:
        for nudge in result.nudge_set.nudges:
            assert "disease" not in nudge.insight.summary.lower()
