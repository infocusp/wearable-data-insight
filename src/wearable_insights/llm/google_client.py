"""Shared Google GenAI client factory — Gemini Developer API or Vertex AI.

Prefers ``GEMINI_API_KEY`` (AI Studio key, no GCP service account needed —
used for hosted deploys) and falls back to Vertex AI via ``GCP_PROJECT``
(used for local dev with `gcloud auth application-default login`).
"""

from __future__ import annotations

from ..config import GCP_LOCATION, GCP_PROJECT
from .keys import resolve_gemini_key


def make_google_client():
    from google import genai

    gemini_key = resolve_gemini_key()
    if gemini_key:
        return genai.Client(api_key=gemini_key)
    if GCP_PROJECT:
        return genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_LOCATION)
    raise RuntimeError(
        "Neither GEMINI_API_KEY nor GCP_PROJECT is set. "
        "Set GEMINI_API_KEY (AI Studio) or GCP_PROJECT (Vertex AI) before using a Gemini model."
    )
