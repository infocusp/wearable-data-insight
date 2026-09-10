"""Unit: per-request LLM credentials are isolated and never leak between requests.

The sidecar accepts a caller-supplied API key, so cross-contamination between concurrent
requests would be a credential-disclosure bug. ``ContextVar`` is the mechanism; these
tests are the proof.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from wearable_insights.llm import keys


@pytest.fixture(autouse=True)
def _clean_context():
    keys.reset_request_keys()
    yield
    keys.reset_request_keys()


def test_falls_back_to_environment_when_unset():
    """With no override bound, resolution must match the module-level config value."""
    assert keys.resolve_gemini_key() == keys.GEMINI_API_KEY
    assert keys.resolve_anthropic_key() == keys.ANTHROPIC_API_KEY


def test_override_takes_precedence():
    keys.set_request_keys(gemini="per-request-key")
    assert keys.resolve_gemini_key() == "per-request-key"


def test_empty_value_does_not_clear_the_fallback():
    """A request that omits the key must inherit the environment, not blank it out."""
    keys.set_request_keys(gemini="")
    assert keys.resolve_gemini_key() == keys.GEMINI_API_KEY


def test_providers_are_independent():
    keys.set_request_keys(gemini="g-key")
    assert keys.resolve_gemini_key() == "g-key"
    assert keys.resolve_anthropic_key() == keys.ANTHROPIC_API_KEY


def test_concurrent_contexts_do_not_cross_contaminate():
    """Two threads binding different keys must each read back their own."""

    def bind_and_read(value: str) -> str:
        # Each worker runs in its own context copy, exactly as a threadpooled
        # FastAPI handler does.
        keys.set_request_keys(gemini=value)
        return keys.resolve_gemini_key() or ""

    expected = [f"key-{i}" for i in range(24)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        import contextvars

        futures = []
        for value in expected:
            ctx = contextvars.copy_context()
            futures.append(pool.submit(ctx.run, bind_and_read, value))
        results = [f.result() for f in futures]

    assert results == expected


def test_google_client_reads_through_the_resolver(monkeypatch):
    """make_google_client must use the per-request key, not the import-time global."""
    from wearable_insights.llm import google_client

    captured: dict[str, str] = {}

    class FakeClient:
        def __init__(self, api_key=None, **kwargs):
            captured["api_key"] = api_key

    fake_genai = type("genai", (), {"Client": FakeClient})
    monkeypatch.setitem(
        __import__("sys").modules, "google", type("google", (), {"genai": fake_genai})
    )
    monkeypatch.setattr(google_client, "resolve_gemini_key", lambda: "request-scoped")

    google_client.make_google_client()
    assert captured["api_key"] == "request-scoped"


def test_service_token_rejects_missing_and_wrong(monkeypatch):
    from fastapi import HTTPException

    from wearable_insights.api_deps import require_service_token

    monkeypatch.setenv("WEARABLE_API_TOKEN", "correct")
    require_service_token("correct")  # must not raise

    for bad in (None, "", "incorrect"):
        with pytest.raises(HTTPException) as exc:
            require_service_token(bad)
        assert exc.value.status_code == 401


def test_service_token_unconfigured_is_503(monkeypatch):
    from fastapi import HTTPException

    from wearable_insights.api_deps import require_service_token

    monkeypatch.delenv("WEARABLE_API_TOKEN", raising=False)
    with pytest.raises(HTTPException) as exc:
        require_service_token("anything")
    assert exc.value.status_code == 503
