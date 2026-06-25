"""Contract test: NudgeSet Pydantic model ↔ nudge.schema.json (T008)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import jsonschema
import pytest

from wearable_insights.config import DISCLAIMER
from wearable_insights.models import (
    Anomaly,
    AnomalyCode,
    AnomalySeverity,
    AnomalyTheme,
    Insight,
    Nudge,
    NudgeSet,
)

_CONTRACTS = Path(__file__).parents[2] / "specs/002-nudges-chatbot/contracts"


def _build_validator() -> jsonschema.Validator:
    """Validator with cross-schema $ref resolution for nudge → anomaly."""
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    nudge_schema = json.loads((_CONTRACTS / "nudge.schema.json").read_text())
    anomaly_schema = json.loads((_CONTRACTS / "anomaly.schema.json").read_text())

    registry = Registry().with_resources([
        (nudge_schema["$id"], Resource.from_contents(nudge_schema, default_specification=DRAFT202012)),
        (anomaly_schema["$id"], Resource.from_contents(anomaly_schema, default_specification=DRAFT202012)),
        # Also register anomaly under its relative name so nudge's "$ref": "anomaly.schema.json" resolves
        ("https://wearable-insights/contracts/anomaly.schema.json", Resource.from_contents(anomaly_schema, default_specification=DRAFT202012)),
    ])
    return jsonschema.Draft202012Validator(nudge_schema, registry=registry)


_VALIDATOR = _build_validator()


def _stub_insight() -> Insight:
    return Insight(
        title="Stress spike",
        summary="Your stress may be linked to reduced recovery this week.",
        action="Take a 10-minute walk this evening.",
        confidence="high",
        source_signals=["stress"],
    )


def _stub_anomaly() -> Anomaly:
    return Anomaly(
        code=AnomalyCode.stress_elevated,
        theme=AnomalyTheme.stress,
        severity=AnomalySeverity.critical,
        signals=["stress"],
        evaluation_tag="Critically Elevated",
        detail="stress 343% above 30-day baseline",
    )


def _stub_nudge(idx: int = 0) -> Nudge:
    return Nudge(
        nudge_id=f"usr_recovery_deficit_2026-06-17_stress_{idx}",
        user_id="usr_recovery_deficit",
        analysis_date=date(2026, 6, 17),
        theme=AnomalyTheme.stress,
        severity=AnomalySeverity.critical,
        anomalies=[_stub_anomaly()],
        insight=_stub_insight(),
        disclaimer=DISCLAIMER,
        triggered_by=["stress"],
    )


def _stub_nudge_set(n: int = 1) -> NudgeSet:
    return NudgeSet(
        user_id="usr_recovery_deficit",
        analysis_date=date(2026, 6, 17),
        nudges=[_stub_nudge(i) for i in range(n)],
    )


def test_valid_nudge_set_validates():
    ns = _stub_nudge_set(1)
    instance = json.loads(ns.model_dump_json())
    _VALIDATOR.validate(instance)


def test_empty_nudge_set_validates():
    ns = NudgeSet(
        user_id="u1",
        analysis_date=date(2026, 6, 17),
        nudges=[],
    )
    _VALIDATOR.validate(json.loads(ns.model_dump_json()))


def test_nudge_set_at_max_cap_validates():
    ns = _stub_nudge_set(3)
    _VALIDATOR.validate(json.loads(ns.model_dump_json()))


def test_nudge_set_exceeding_schema_max_fails():
    """JSON schema enforces maxItems: 3; 4 nudges should fail validation."""
    ns = _stub_nudge_set(3)
    instance = json.loads(ns.model_dump_json())
    extra = json.loads(_stub_nudge(99).model_dump_json())
    instance["nudges"].append(extra)
    with pytest.raises(jsonschema.ValidationError):
        _VALIDATOR.validate(instance)


def test_pydantic_cap_rejects_too_many_nudges():
    """Pydantic model_validator also rejects > MAX_NUDGES_PER_DAY nudges."""
    with pytest.raises(Exception, match="MAX_NUDGES_PER_DAY"):
        NudgeSet(
            user_id="u1",
            analysis_date=date(2026, 6, 17),
            nudges=[_stub_nudge(i) for i in range(4)],
        )


def test_nudge_requires_at_least_one_anomaly():
    with pytest.raises(Exception):
        Nudge(
            nudge_id="n1",
            user_id="u1",
            analysis_date=date(2026, 6, 17),
            theme=AnomalyTheme.stress,
            severity=AnomalySeverity.critical,
            anomalies=[],
            insight=_stub_insight(),
            disclaimer=DISCLAIMER,
            triggered_by=["stress"],
        )
