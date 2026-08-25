"""Integration: the API surface is stateless, deterministic, and date-explicit.

These are the load-bearing guarantees of the sidecar design, so they are asserted
directly rather than inferred:

* identical request  ⇒ identical response bytes (no hidden per-process state);
* live episode/cooldown state round-trips through the request body;
* no handler consults ``date.today()``, so responses cannot drift at UTC midnight.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

TOKEN = "test-service-token"
HEADERS = {"X-Wearable-Token": TOKEN}
PROFILE = {"persona": "recovery_deficit", "end_date": "2026-08-25"}


@pytest.fixture(scope="module")
def client():
    os.environ["WEARABLE_API_TOKEN"] = TOKEN
    from wearable_insights.api import app

    with TestClient(app) as c:
        yield c


# ── Determinism ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path,body",
    [
        ("/v1/comparison", {"profile": PROFILE}),
        ("/v1/underwriting/signals", {"profile": PROFILE}),
        ("/v1/wellness/streaks", {"profile": PROFILE}),
        (
            "/v1/drowsiness/assess",
            {"profile": PROFILE, "incident_at": "2026-08-25T07:40", "continuous_drive_minutes": 75},
        ),
        ("/v1/attestation/mock", {"profile": PROFILE}),
    ],
)
def test_identical_request_yields_identical_bytes(client, path, body):
    first = client.post(path, json=body, headers=HEADERS)
    second = client.post(path, json=body, headers=HEADERS)
    assert first.status_code == 200
    assert first.content == second.content, f"{path} is not byte-deterministic"


def test_end_date_drives_the_window_not_the_wall_clock(client):
    """Two different end_dates must produce different analyses — proving the request,
    not the process clock, selects the window."""
    a = client.post(
        "/v1/comparison",
        json={"profile": {**PROFILE, "end_date": "2026-08-25"}},
        headers=HEADERS,
    ).json()
    b = client.post(
        "/v1/comparison",
        json={"profile": {**PROFILE, "end_date": "2026-06-17"}},
        headers=HEADERS,
    ).json()
    assert a["comparison"]["analysis_date"] == "2026-08-25"
    assert b["comparison"]["analysis_date"] == "2026-06-17"
    assert a != b


def test_end_date_is_required():
    """A ProfileRef without end_date must be rejected, not silently defaulted to today."""
    from pydantic import ValidationError

    from wearable_insights.api_models import ProfileRef

    with pytest.raises(ValidationError):
        ProfileRef(persona="recovery_deficit")


def test_no_handler_calls_date_today(client, monkeypatch):
    """Guard against ``date.today()`` creeping back into a request path."""
    import wearable_insights.data.slotted_baselines as sb

    calls: list[str] = []
    real_today = sb.date.today

    class Tripwire(sb.date):  # type: ignore[misc,valid-type]
        @classmethod
        def today(cls):  # pragma: no cover — should never fire
            calls.append("today")
            return real_today()

    monkeypatch.setattr(sb, "date", Tripwire)
    client.post("/v1/comparison", json={"profile": PROFILE}, headers=HEADERS)
    client.post(
        "/v1/live/tick",
        json={"profile": PROFILE, "llm": {"skip_llm": True}, "now": 1000.0},
        headers=HEADERS,
    )
    assert calls == [], "a request path called date.today()"


# ── Live state round-trip ─────────────────────────────────────────────────────


def test_cursor_advances_in_the_response(client):
    body = {
        "profile": PROFILE,
        "cursor": {"mode": "stressed", "device_minute": 480, "step": 5},
        "llm": {"skip_llm": True},
        "now": 1000.0,
    }
    data = client.post("/v1/live/tick", json=body, headers=HEADERS).json()
    assert data["cursor"]["device_minute"] == 485
    assert data["day_type"] in {"weekday", "weekend"}
    assert len(data["samples"]) == 48


def test_returned_nudge_state_suppresses_a_repeat_raise(client):
    """An anomaly already active in the caller-supplied state must not raise again."""
    body = {
        "profile": PROFILE,
        "cursor": {"mode": "stressed", "device_minute": 480},
        "llm": {"skip_llm": True},
        "now": 1000.0,
    }
    first = client.post("/v1/live/tick", json=body, headers=HEADERS).json()
    raised = {a["code"] for a in first["new_anomalies"]}
    assert raised, "expected the stressed context to raise at least one anomaly"

    # Replay the *same* cursor so the same anomalies are detected, carrying state forward.
    second = client.post(
        "/v1/live/tick",
        json={**body, "nudge_state": first["nudge_state"], "now": 1010.0},
        headers=HEADERS,
    ).json()
    reraised = {a["code"] for a in second["new_anomalies"]}
    assert not (raised & reraised), f"{raised & reraised} re-raised despite active state"


def test_state_is_not_retained_between_requests(client):
    """Omitting nudge_state must reset dedup — proving the service holds nothing itself."""
    body = {
        "profile": PROFILE,
        "cursor": {"mode": "stressed", "device_minute": 480},
        "llm": {"skip_llm": True},
        "now": 1000.0,
    }
    first = client.post("/v1/live/tick", json=body, headers=HEADERS).json()
    again = client.post("/v1/live/tick", json=body, headers=HEADERS).json()
    assert first["new_anomalies"] == again["new_anomalies"]


# ── Auth ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("headers", [{}, {"X-Wearable-Token": "wrong"}])
def test_missing_or_wrong_token_is_401(client, headers):
    assert client.post("/v1/comparison", json={"profile": PROFILE}, headers=headers).status_code == 401


def test_health_needs_no_token_and_leaks_no_secret(client):
    response = client.get("/v1/health")
    assert response.status_code == 200
    body = response.text
    assert TOKEN not in body
    assert "API_KEY" not in body


def test_ingest_is_explicitly_not_implemented(client):
    response = client.post("/ingest", headers=HEADERS)
    assert response.status_code == 501
    assert response.json()["error"] == "not_implemented"
