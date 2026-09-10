"""FastAPI dependencies: service authentication and per-request LLM credentials."""

from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException

from .llm.keys import set_request_keys


def require_service_token(x_wearable_token: str | None = Header(None)) -> None:
    """Constant-time shared-secret check.

    Applied as a router-level dependency so a newly added endpoint cannot forget it.
    This is defence-in-depth, not the perimeter: the service is server-to-server only
    and registers no CORS middleware, so a browser cannot reach it at all.
    """
    expected = os.environ.get("WEARABLE_API_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="WEARABLE_API_TOKEN is not configured")
    # The header is declared optional so that a *missing* token is rejected as 401 like an
    # incorrect one, rather than leaking the difference as a 422 validation error.
    if not x_wearable_token or not hmac.compare_digest(x_wearable_token, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing service token")


def llm_key_context(
    x_llm_api_key: str | None = Header(None),
    x_llm_provider: str | None = Header(None),
) -> None:
    """Bind a caller-supplied LLM key to this request's context.

    The key travels in a **header, never the body** — request bodies surface in access
    logs and in FastAPI's 422 validation dumps, headers are easy to redact.  When absent,
    the resolvers fall back to the sidecar's own environment credential, so scheduled and
    server-initiated calls work without a browser-held key.
    """
    if not x_llm_api_key:
        return
    provider = (x_llm_provider or "google").lower()
    if provider == "anthropic":
        set_request_keys(anthropic=x_llm_api_key)
    else:
        set_request_keys(gemini=x_llm_api_key)
