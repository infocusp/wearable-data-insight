"""Per-request LLM credential overrides (ClaimGuard integration).

``config.py`` reads ``GEMINI_API_KEY`` / ``ANTHROPIC_API_KEY`` into module globals at
import time, which is correct for the Streamlit app (one process, one operator) but
cannot serve the FastAPI sidecar: ClaimGuard holds its Gemini key in the browser's
``localStorage`` and forwards it per request.

A ``ContextVar`` gives each request its own credential without changing a single public
signature.  When nothing is set — which is always the case under Streamlit and in the
existing test suite — the resolvers fall through to the module globals, so behaviour is
byte-for-byte unchanged.

``ContextVar`` values are copied into FastAPI's threadpool workers automatically, so
``def`` (blocking) handlers see the value set by their dependency.
"""

from __future__ import annotations

from contextvars import ContextVar

from ..config import ANTHROPIC_API_KEY, GEMINI_API_KEY

_gemini_override: ContextVar[str | None] = ContextVar("wearable_gemini_key", default=None)
_anthropic_override: ContextVar[str | None] = ContextVar("wearable_anthropic_key", default=None)


def set_request_keys(gemini: str | None = None, anthropic: str | None = None) -> None:
    """Bind caller-supplied credentials to the current context.

    Empty/None values are ignored rather than clearing the override, so a request that
    omits a key transparently inherits the sidecar's own environment credential.
    """
    if gemini:
        _gemini_override.set(gemini)
    if anthropic:
        _anthropic_override.set(anthropic)


def reset_request_keys() -> None:
    """Clear both overrides for the current context (used by tests)."""
    _gemini_override.set(None)
    _anthropic_override.set(None)


def resolve_gemini_key() -> str | None:
    """Per-request Gemini key if one was bound, else the environment key."""
    return _gemini_override.get() or GEMINI_API_KEY


def resolve_anthropic_key() -> str | None:
    """Per-request Anthropic key if one was bound, else the environment key."""
    return _anthropic_override.get() or ANTHROPIC_API_KEY
