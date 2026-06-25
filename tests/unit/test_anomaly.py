"""Golden + unit tests for anomaly detection (T010, SC-002, SC-006)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from wearable_insights.anomaly import detect_anomalies
from wearable_insights.data.synthetic import build_recovery_deficit_snapshot, generate_synthetic_profile
from wearable_insights.models import (
    AnomalySeverity,
    ComparisonObject,
    DataQuality,
    MetricComparison,
    WindowComparison,
)
from wearable_insights.normalize import normalize_profile
from wearable_insights.pipeline import build_comparison

_FIXTURES = Path(__file__).parents[1] / "fixtures/phase2"

# ── Golden expected output for recovery-deficit day ──────────────────────────
# Generated from build_recovery_deficit_snapshot(seed=42, days=31).
# Verify with: pytest tests/unit/test_anomaly.py -v
_DEFICIT_EXPECTED_CODES = {
    "stress_elevated",
    "hrv_depressed",
    "steps_low",
    "active_minutes_low",
    "sleep_insufficient",
    "sleep_quality_low",
}

_DEFICIT_EXPECTED_SEVERITIES = {
    "stress_elevated": AnomalySeverity.critical,    # 342.9% above baseline
    "hrv_depressed": AnomalySeverity.significant,   # -35.6% (30–50 % band)
    "steps_low": AnomalySeverity.critical,           # -100%
    "active_minutes_low": AnomalySeverity.critical,  # -100%
    "sleep_insufficient": AnomalySeverity.significant,  # -33.4%
    "sleep_quality_low": AnomalySeverity.critical,   # -64.0%
}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def deficit_comparison() -> ComparisonObject:
    raw = build_recovery_deficit_snapshot(seed=42, days=31)
    return build_comparison(normalize_profile(raw))


@pytest.fixture(scope="module")
def clean_comparison() -> ComparisonObject:
    """Programmatic clean-day fixture: all monthly metrics stable."""
    stable_win = WindowComparison(
        baseline_value=100.0,
        percentage_change=2.0,
        trend="stable",
        evaluation_tag="Stable / Within Normal Baseline",
    )
    mc = MetricComparison(
        current_value=102.0,
        weekly=stable_win,
        monthly=stable_win,
        weekday=stable_win,
        sixty_day=stable_win,
        ninety_day=stable_win,
        flags=[],
    )
    return ComparisonObject(
        user_id="usr_clean",
        analysis_date=date(2026, 6, 17),
        sleep={
            "sleep_duration": mc,
            "sleep_score": mc,
            "deep_sleep": mc,
            "rem_sleep": mc,
        },
        heart_health={
            "resting_hr": mc,
            "hrv": mc,
            "stress": mc,
        },
        activity={
            "steps": mc,
            "active_minutes": mc,
        },
        data_quality=DataQuality(),
    )


# ── Happy path ────────────────────────────────────────────────────────────────

def test_detect_anomalies_returns_list(deficit_comparison):
    result = detect_anomalies(deficit_comparison)
    assert isinstance(result, list)


# ── Golden test: recovery-deficit day ────────────────────────────────────────

def test_recovery_deficit_produces_all_expected_codes(deficit_comparison):
    """SC-006: exact anomaly codes for the seeded recovery-deficit fixture."""
    anomalies = detect_anomalies(deficit_comparison)
    codes = {a.code.value for a in anomalies}
    assert codes == _DEFICIT_EXPECTED_CODES


def test_recovery_deficit_produces_correct_severities(deficit_comparison):
    anomalies = detect_anomalies(deficit_comparison)
    by_code = {a.code.value: a.severity for a in anomalies}
    for code, expected_sev in _DEFICIT_EXPECTED_SEVERITIES.items():
        assert by_code[code] == expected_sev, (
            f"{code}: expected {expected_sev}, got {by_code.get(code)}"
        )


def test_anomalies_have_non_empty_signals(deficit_comparison):
    for anomaly in detect_anomalies(deficit_comparison):
        assert len(anomaly.signals) >= 1, f"{anomaly.code} has no signals"


def test_anomalies_have_non_empty_detail(deficit_comparison):
    for anomaly in detect_anomalies(deficit_comparison):
        assert anomaly.detail.strip(), f"{anomaly.code} has empty detail"


def test_anomalies_theme_matches_code(deficit_comparison):
    """Each code fires on its declared theme."""
    _CODE_THEME = {
        "stress_elevated": "stress",
        "hrv_depressed": "recovery",
        "steps_low": "activity",
        "active_minutes_low": "activity",
        "sleep_insufficient": "sleep",
        "sleep_quality_low": "sleep",
    }
    for anomaly in detect_anomalies(deficit_comparison):
        expected = _CODE_THEME[anomaly.code.value]
        assert anomaly.theme.value == expected


# ── SC-002: clean day → no anomalies ─────────────────────────────────────────

def test_clean_day_produces_no_anomalies(clean_comparison):
    """SC-002: all-within-baseline day yields an empty Anomaly list."""
    assert detect_anomalies(clean_comparison) == []


def test_healthy_consistent_profile_produces_no_anomalies():
    """SC-002 with the synthetic healthy_consistent profile (31-day window)."""
    raw = generate_synthetic_profile("healthy_consistent", seed=42, days=31)
    comparison = build_comparison(normalize_profile(raw))
    anomalies = detect_anomalies(comparison)
    assert anomalies == [], (
        f"Expected no anomalies for healthy_consistent, got: {[a.code for a in anomalies]}"
    )


# ── SC-006: reproducibility ───────────────────────────────────────────────────

def test_anomaly_detection_is_reproducible(deficit_comparison):
    """SC-006: same input always yields identical Anomaly list."""
    result1 = detect_anomalies(deficit_comparison)
    result2 = detect_anomalies(deficit_comparison)
    assert [a.model_dump() for a in result1] == [a.model_dump() for a in result2]


# ── Golden fixture from JSON ──────────────────────────────────────────────────

def test_fixture_json_produces_same_anomalies():
    """Anomalies from the saved JSON fixture match the programmatic comparison."""
    fixture_path = _FIXTURES / "recovery_deficit_comparison.json"
    comparison = ComparisonObject.model_validate_json(fixture_path.read_text())
    anomalies = detect_anomalies(comparison)
    codes = {a.code.value for a in anomalies}
    assert codes == _DEFICIT_EXPECTED_CODES
