"""Contract test: Anomaly Pydantic model ↔ anomaly.schema.json (T007)."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from wearable_insights.models import Anomaly, AnomalyCode, AnomalySeverity, AnomalyTheme

_CONTRACTS = Path(__file__).parents[2] / "specs/002-nudges-chatbot/contracts"
_SCHEMA = json.loads((_CONTRACTS / "anomaly.schema.json").read_text())


def _validate(instance: dict) -> None:
    jsonschema.validate(instance, _SCHEMA)


def _anomaly(**overrides) -> Anomaly:
    base = dict(
        code=AnomalyCode.stress_elevated,
        theme=AnomalyTheme.stress,
        severity=AnomalySeverity.critical,
        signals=["stress"],
        evaluation_tag="Critically Elevated",
        detail="stress 343% above 30-day baseline",
    )
    base.update(overrides)
    return Anomaly(**base)


def test_valid_anomaly_validates_against_schema():
    a = _anomaly()
    _validate(json.loads(a.model_dump_json()))


@pytest.mark.parametrize("code", [e.value for e in AnomalyCode])
def test_all_codes_accepted_by_schema(code):
    a = _anomaly(code=code)
    _validate(json.loads(a.model_dump_json()))


@pytest.mark.parametrize("theme", [e.value for e in AnomalyTheme])
def test_all_themes_accepted_by_schema(theme):
    a = _anomaly(theme=theme)
    _validate(json.loads(a.model_dump_json()))


@pytest.mark.parametrize("severity", [e.value for e in AnomalySeverity])
def test_all_severities_accepted_by_schema(severity):
    a = _anomaly(severity=severity)
    _validate(json.loads(a.model_dump_json()))


def test_schema_requires_at_least_one_signal():
    a = _anomaly()
    instance = json.loads(a.model_dump_json())
    instance["signals"] = []
    with pytest.raises(jsonschema.ValidationError):
        _validate(instance)


def test_schema_rejects_unknown_code():
    a = _anomaly()
    instance = json.loads(a.model_dump_json())
    instance["code"] = "nonexistent_code"
    with pytest.raises(jsonschema.ValidationError):
        _validate(instance)


def test_schema_rejects_missing_required_field():
    a = _anomaly()
    instance = json.loads(a.model_dump_json())
    del instance["detail"]
    with pytest.raises(jsonschema.ValidationError):
        _validate(instance)


def test_pydantic_rejects_missing_signal():
    with pytest.raises(Exception):
        Anomaly(
            code="stress_elevated",
            theme="stress",
            severity="critical",
            signals=[],
            evaluation_tag="Critically Elevated",
            detail="test",
        )
