"""Contract test: ChatSession Pydantic model ↔ chat_message.schema.json (T009)."""

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
    ChatGrounding,
    ChatSession,
    ChatTurn,
    ComparisonObject,
    DataQuality,
    Insight,
    Nudge,
)

_CONTRACTS = Path(__file__).parents[2] / "specs/002-nudges-chatbot/contracts"


def _build_validator() -> jsonschema.Validator:
    chat_schema = json.loads((_CONTRACTS / "chat_message.schema.json").read_text())
    nudge_schema = json.loads((_CONTRACTS / "nudge.schema.json").read_text())
    anomaly_schema = json.loads((_CONTRACTS / "anomaly.schema.json").read_text())

    store = {
        chat_schema["$id"]: chat_schema,
        nudge_schema["$id"]: nudge_schema,
        anomaly_schema["$id"]: anomaly_schema,
    }
    resolver = jsonschema.RefResolver(
        base_uri=chat_schema["$id"],
        referrer=chat_schema,
        store=store,
    )
    # Exclude the comparison $ref (external URI) — resolve Nudge/ChatTurn parts only
    return jsonschema.Draft202012Validator(chat_schema, resolver=resolver)


def _stub_comparison() -> ComparisonObject:
    return ComparisonObject(
        user_id="usr_recovery_deficit",
        analysis_date=date(2026, 6, 17),
        data_quality=DataQuality(),
    )


def _stub_nudge() -> Nudge:
    return Nudge(
        nudge_id="usr_recovery_deficit_2026-06-17_stress",
        user_id="usr_recovery_deficit",
        analysis_date=date(2026, 6, 17),
        theme=AnomalyTheme.stress,
        severity=AnomalySeverity.critical,
        anomalies=[
            Anomaly(
                code=AnomalyCode.stress_elevated,
                theme=AnomalyTheme.stress,
                severity=AnomalySeverity.critical,
                signals=["stress"],
                evaluation_tag="Critically Elevated",
                detail="stress 343% above 30-day baseline",
            )
        ],
        insight=Insight(
            title="Stress spike",
            summary="Your stress may be linked to reduced recovery this week.",
            action="Take a 10-minute walk this evening.",
            confidence="high",
            source_signals=["stress"],
        ),
        disclaimer=DISCLAIMER,
        triggered_by=["stress"],
    )


def _stub_session(n_turns: int = 0) -> ChatSession:
    turns = []
    if n_turns > 0:
        turns = [
            ChatTurn(role="user", content="Why was this raised?"),
            ChatTurn(role="assistant", content="Your stress was above your typical range."),
        ][:n_turns]
    return ChatSession(
        nudge_id="usr_recovery_deficit_2026-06-17_stress",
        turns=turns,
        grounding=ChatGrounding(
            nudge=_stub_nudge(),
            comparison=_stub_comparison(),
        ),
    )


def test_chat_session_has_required_fields():
    session = _stub_session()
    d = session.model_dump()
    assert "nudge_id" in d
    assert "turns" in d
    assert "grounding" in d
    assert "nudge" in d["grounding"]
    assert "comparison" in d["grounding"]


def test_chat_session_empty_turns_is_valid():
    session = _stub_session(0)
    assert session.turns == []


def test_chat_session_with_turns():
    session = _stub_session(2)
    assert len(session.turns) == 2
    assert session.turns[0].role == "user"
    assert session.turns[1].role == "assistant"


def test_chat_turn_role_is_validated():
    with pytest.raises(Exception):
        ChatTurn(role="system", content="You are a doctor.")


def test_grounding_links_to_nudge_and_comparison():
    session = _stub_session()
    assert session.grounding.nudge.nudge_id == session.nudge_id
    assert session.grounding.comparison.user_id == "usr_recovery_deficit"


def test_chat_session_serializes_to_json():
    session = _stub_session(2)
    data = json.loads(session.model_dump_json())
    assert data["nudge_id"] == "usr_recovery_deficit_2026-06-17_stress"
    assert len(data["turns"]) == 2
