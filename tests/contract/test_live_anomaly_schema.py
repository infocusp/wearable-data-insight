"""Contract test: live anomalies validate against contracts/live_anomaly.schema.json."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from wearable_insights.config import LIVE_BUFFER_POINTS
from wearable_insights.live_anomaly import detect_live_anomalies

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "specs"
    / "003-live-auto-nudges"
    / "contracts"
    / "live_anomaly.schema.json"
)

_ANCHORS = {"hr": 70.0, "hrv": 55.0, "spo2": 97.6, "skin_temp": 36.7, "resp_rate": 14.0}


def _flat_buffer(**overrides):
    base = dict(_ANCHORS)
    base.update(overrides)
    return [{"minute": i, **base} for i in range(LIVE_BUFFER_POINTS)]


def test_live_anomalies_match_contract() -> None:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    buf = _flat_buffer(hr=92.0, spo2=94.0, skin_temp=37.7, resp_rate=18.0)
    anomalies = detect_live_anomalies(buf, _ANCHORS)
    assert anomalies, "expected several anomalies for an all-off buffer"
    for anomaly in anomalies:
        jsonschema.validate(anomaly.model_dump(mode="json"), schema)
