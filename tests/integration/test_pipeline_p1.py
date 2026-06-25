"""Integration test: end-to-end pipeline with a stubbed LLM client (SC-001).

Uses the built-in recovery-deficit snapshot (FR-002). No ANTHROPIC_API_KEY needed.
"""

from __future__ import annotations

from datetime import date

import pytest

from wearable_insights.config import DISCLAIMER
from wearable_insights.data.synthetic import build_recovery_deficit_snapshot
from wearable_insights.models import ComparisonObject, Insight, InsightSet
from wearable_insights.normalize import normalize_profile
from wearable_insights.pipeline import PipelineResult, build_comparison, run_pipeline
from wearable_insights.safety import SafetyError


# ── Canned stub InsightSet ────────────────────────────────────────────────────

_STUB_INSIGHT_SET = InsightSet(
    insights=[
        Insight(
            title="Recovery under strain",
            summary=(
                "Your HRV is notably below your recent baseline, which may be "
                "associated with how your body is managing the physical and "
                "psychological load from this week. Sleep and activity patterns "
                "appear to be co-occurring with this recovery shift."
            ),
            action="Aim for at least 8 hours of sleep tonight and avoid intense exercise.",
            confidence="high",
            source_signals=["hrv", "sleep_duration", "stress"],
        )
    ],
    disclaimer=DISCLAIMER,
    generated_from=["hrv", "sleep_duration", "stress"],
    schema_version="1.0",
)


def _stub_generate(comparison: ComparisonObject) -> InsightSet:
    return _STUB_INSIGHT_SET


# ── build_comparison (deterministic only) ────────────────────────────────────


def test_build_comparison_recovery_deficit():
    raw = build_recovery_deficit_snapshot(seed=42, days=31)
    comparison = build_comparison(raw)
    assert comparison.user_id == "usr_recovery_deficit"
    assert isinstance(comparison.analysis_date, date)
    # The deficit profile has a very bad last day — expect at least some signals down
    combined = {**comparison.sleep, **comparison.heart_health, **comparison.activity}
    trends = {name: mc.monthly.trend for name, mc in combined.items()}
    # Should have at least one non-stable trend given the extreme profile
    assert any(t != "stable" for t in trends.values()), (
        f"Expected some non-stable trend in recovery_deficit, got: {trends}"
    )


def test_build_comparison_accepts_normalized_profile():
    raw = build_recovery_deficit_snapshot(seed=42, days=31)
    profile = normalize_profile(raw)
    comparison = build_comparison(profile)
    assert comparison.user_id == "usr_recovery_deficit"


def test_build_comparison_accepts_date_string():
    raw = build_recovery_deficit_snapshot(seed=42, days=31)
    profile = normalize_profile(raw)
    analysis = profile.records[-1].date.isoformat()
    comparison = build_comparison(profile, analysis)
    assert comparison.analysis_date == profile.records[-1].date


# ── run_pipeline – no LLM ────────────────────────────────────────────────────


def test_run_pipeline_without_generate_fn_returns_comparison_only():
    raw = build_recovery_deficit_snapshot(seed=42, days=31)
    result = run_pipeline(raw, generate_fn=None)
    assert isinstance(result, PipelineResult)
    assert result.comparison is not None
    assert result.insight_set is None
    assert result.error is None


# ── run_pipeline – stub LLM ──────────────────────────────────────────────────


def test_run_pipeline_with_stub_returns_valid_insight():
    raw = build_recovery_deficit_snapshot(seed=42, days=31)
    result = run_pipeline(raw, generate_fn=_stub_generate)
    assert result.success
    assert result.insight_set is not None
    assert len(result.insight_set.insights) >= 1
    assert result.error is None


def test_run_pipeline_insight_has_required_fields():
    raw = build_recovery_deficit_snapshot(seed=42, days=31)
    result = run_pipeline(raw, generate_fn=_stub_generate)
    insight = result.insight_set.insights[0]
    assert insight.title
    assert insight.summary
    assert insight.action
    assert insight.confidence in ("low", "medium", "high")
    assert insight.source_signals


def test_run_pipeline_disclaimer_present():
    raw = build_recovery_deficit_snapshot(seed=42, days=31)
    result = run_pipeline(raw, generate_fn=_stub_generate)
    assert result.insight_set.disclaimer
    assert len(result.insight_set.disclaimer) > 10


# ── run_pipeline – retry on SafetyError ──────────────────────────────────────


def test_run_pipeline_retries_on_safety_failure():
    call_count = 0

    def _bad_then_good(comparison: ComparisonObject) -> InsightSet:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call returns an unsafe response
            return InsightSet(
                insights=[
                    Insight(
                        title="Bad",
                        summary="This disease causes your fatigue.",
                        action="See a doctor.",
                        confidence="low",
                        source_signals=["hrv"],
                    )
                ],
                disclaimer=DISCLAIMER,
                generated_from=["hrv"],
            )
        return _STUB_INSIGHT_SET

    raw = build_recovery_deficit_snapshot(seed=42, days=31)
    result = run_pipeline(raw, generate_fn=_bad_then_good, max_retries=2)
    assert call_count == 2
    assert result.success


def test_run_pipeline_fails_gracefully_after_max_retries():
    def _always_bad(comparison: ComparisonObject) -> InsightSet:
        return InsightSet(
            insights=[
                Insight(
                    title="Bad",
                    summary="This disease is causing your fatigue.",
                    action="Treat the disease immediately.",
                    confidence="low",
                    source_signals=["hrv"],
                )
            ],
            disclaimer=DISCLAIMER,
            generated_from=["hrv"],
        )

    raw = build_recovery_deficit_snapshot(seed=42, days=31)
    result = run_pipeline(raw, generate_fn=_always_bad, max_retries=1)
    assert not result.success
    assert result.error is not None
    assert result.comparison is not None  # comparison still available


# ── run_pipeline – JSON dump ──────────────────────────────────────────────────


def test_run_pipeline_dumps_comparison_to_json(tmp_path):
    raw = build_recovery_deficit_snapshot(seed=42, days=31)
    out_path = tmp_path / "comparison.json"
    run_pipeline(raw, generate_fn=_stub_generate, dump_comparison=out_path)
    assert out_path.exists()
    content = out_path.read_text()
    assert "user_id" in content
    assert "analysis_date" in content


# ── Determinism ───────────────────────────────────────────────────────────────


def test_comparison_deterministic_across_runs():
    raw = build_recovery_deficit_snapshot(seed=42, days=31)
    co1 = build_comparison(raw)
    co2 = build_comparison(raw)
    assert co1.model_dump_json() == co2.model_dump_json()
