"""Agent memory — what the chatbot carries forward across conversations.

Three flavours of memory feed the chat grounding (see
:func:`build_memory_block`):

1. **User-stated facts & preferences** — durable things the *user* told the bot
   ("works night shifts", "prefers morning runs").  Extracted by the LLM from a
   finished conversation and stored via :mod:`wearable_insights.store`.
2. **Conversation summaries** — a one-line recap of each past chat, also
   LLM-produced at the end of a session.
3. **Recurring data patterns** — deterministic, computed on demand from the raw
   record history (never from the LLM), e.g. "short sleep on 3 of the last 7 days".

Facts and summaries are persisted; patterns are recomputed each time.  All of this
stays associative/informational and never becomes diagnostic.
"""

from __future__ import annotations

import json
from datetime import date

from . import store
from .config import (
    ANTHROPIC_API_KEY,
    CHAT_MODEL,
    GCP_LOCATION,
    GCP_PROJECT,
    MEMORY_MAX_FACTS,
    MEMORY_MAX_SUMMARIES,
    MEMORY_PATTERN_LOOKBACK_DAYS,
    MODEL_OPTIONS,
)

# ── Deterministic recurring patterns ──────────────────────────────────────────

# (record field, predicate, human label) — predicate flags a "rough" day.
_PATTERN_RULES: list[tuple[str, "callable", str]] = [
    ("sleep_duration_minutes", lambda v: v < 360, "short sleep (< 6h)"),
    ("sleep_score", lambda v: v < 60, "low sleep quality"),
    ("stress_score", lambda v: v >= 60, "elevated stress"),
    ("steps", lambda v: v < 5000, "low step count"),
    ("active_minutes", lambda v: v < 20, "few active minutes"),
]


def _as_date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def compute_recurring_patterns(
    profile_dict: dict,
    analysis_date: date,
    lookback_days: int = MEMORY_PATTERN_LOOKBACK_DAYS,
) -> list[str]:
    """Deterministically summarise rough days over the lookback window.

    Scans the raw daily records ending at ``analysis_date`` and reports any
    threshold breach that recurs on **2 or more** days, e.g.
    ``"elevated stress on 4 of the last 7 days"``.  Pure Python, no LLM.
    """
    records = profile_dict.get("records", [])
    window = [
        r for r in records
        if 0 <= (analysis_date - _as_date(r.get("date"))).days < lookback_days
    ]
    n = len(window)
    if n == 0:
        return []

    patterns: list[str] = []
    for field, predicate, label in _PATTERN_RULES:
        hits = sum(
            1 for r in window
            if r.get(field) is not None and predicate(r[field])
        )
        if hits >= 2:
            patterns.append(f"{label} on {hits} of the last {n} days")
    return patterns


# ── LLM-backed extraction ─────────────────────────────────────────────────────

_EXTRACT_SYSTEM = """\
You distil durable memory from a wellness chat so a future conversation can feel \
continuous.  Return STRICT JSON only, no prose, with this shape:

{"facts": ["..."], "summary": "..."}

- "facts": 0–5 short, durable facts or preferences the USER explicitly stated about \
themselves (e.g. "works night shifts", "prefers morning runs", "is cutting evening \
caffeine"). Only include things the user actually said. Do NOT include the bot's \
advice, one-off feelings, medical claims, or metric values. Empty list if none.
- "summary": one neutral sentence recapping what this chat was about. Empty string \
if the chat had no real content.

Never invent facts. Never include diagnoses or clinical language."""


def _complete_text(system: str, user: str, model: str) -> str:
    """Single-shot completion routed by provider; returns plain text."""
    info = MODEL_OPTIONS.get(model)
    if info is None:
        raise ValueError(f"Unknown model '{model}'.")
    provider = info["provider"]

    if provider == "anthropic":
        if not ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        import anthropic

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=model,
            max_tokens=512,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text

    if provider == "google":
        if not GCP_PROJECT:
            raise RuntimeError("GCP_PROJECT is not set.")
        from google import genai
        from google.genai import types

        client = genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_LOCATION)
        resp = client.models.generate_content(
            model=model,
            contents=[{"role": "user", "parts": [{"text": user}]}],
            config=types.GenerateContentConfig(
                system_instruction=system, max_output_tokens=512
            ),
        )
        return resp.text

    raise ValueError(f"Unsupported provider '{provider}'.")


def _parse_extraction(raw: str) -> dict:
    """Best-effort JSON parse of the extraction reply; tolerant of code fences."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {"facts": [], "summary": ""}
    facts = data.get("facts") or []
    summary = (data.get("summary") or "").strip()
    facts = [str(f).strip() for f in facts if str(f).strip()]
    return {"facts": facts, "summary": summary}


def finalize_session(
    session_id: str,
    user_id: str,
    model: str | None = None,
    db_path=None,
) -> dict:
    """Extract durable facts + a one-line summary from a finished chat and persist.

    Called when the user leaves or closes a conversation.  No-op (returns empty)
    if the session has no real user/assistant exchange yet.
    """
    turns = store.get_turns(session_id, db_path=db_path)
    real = [t for t in turns if t["content"].strip()]
    # Need at least one user message to have anything worth remembering.
    if not any(t["role"] == "user" for t in real):
        return {"facts": [], "summary": ""}

    transcript = "\n".join(f"{t['role'].upper()}: {t['content']}" for t in real)
    try:
        raw = _complete_text(_EXTRACT_SYSTEM, transcript, model or CHAT_MODEL)
    except (RuntimeError, ValueError):
        return {"facts": [], "summary": ""}

    parsed = _parse_extraction(raw)
    for fact in parsed["facts"]:
        store.add_memory(
            user_id, "fact", fact, source_session_id=session_id, db_path=db_path
        )
    if parsed["summary"]:
        store.add_memory(
            user_id, "summary", parsed["summary"],
            source_session_id=session_id, db_path=db_path,
        )
    return parsed


# ── Memory block for chat grounding ───────────────────────────────────────────


def build_memory_block(
    user_id: str,
    profile_dict: dict | None = None,
    analysis_date: date | None = None,
    db_path=None,
) -> str:
    """Assemble the user's carried-forward memory into a grounding text block.

    Returns an empty string when there is nothing to remember, so callers can
    cheaply skip injection.
    """
    facts = [m["content"] for m in store.get_memory(user_id, "fact", db_path=db_path)]
    summaries = [
        m["content"] for m in store.get_memory(user_id, "summary", db_path=db_path)
    ]
    patterns: list[str] = []
    if profile_dict is not None and analysis_date is not None:
        patterns = compute_recurring_patterns(profile_dict, analysis_date)

    facts = facts[:MEMORY_MAX_FACTS]
    summaries = summaries[:MEMORY_MAX_SUMMARIES]

    if not (facts or summaries or patterns):
        return ""

    lines: list[str] = ["## What you remember about this user"]
    if facts:
        lines.append("Stated facts & preferences:")
        lines.extend(f"- {f}" for f in facts)
    if patterns:
        lines.append("Recurring patterns in their recent data:")
        lines.extend(f"- {p}" for p in patterns)
    if summaries:
        lines.append("Recent conversations covered:")
        lines.extend(f"- {s}" for s in summaries)
    lines.append(
        "Use this background only to stay continuous and personal. It is associative "
        "context, not new data to diagnose from."
    )
    return "\n".join(lines)
