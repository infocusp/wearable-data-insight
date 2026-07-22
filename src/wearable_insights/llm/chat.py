"""Chat reply function — multi-turn conversation grounded in today's data.

Public API::

    reply_text = chat_reply(history, comparison, nudge=nudge, nudge_set=ns,
                            memory_block=mem, model=None)

Two grounding modes:

* **nudge chat** — pass ``nudge``; the bot is anchored to that one nudge plus the
  metrics that triggered it (Phase 2 behaviour).
* **free chat** — omit ``nudge``; the bot may roam over the whole day's
  ``ComparisonObject`` and any nudges raised that day (``nudge_set``).

``history`` is a plain list of ``{"role": "user"|"assistant", "content": str}`` dicts
(as persisted in :mod:`wearable_insights.store`).  Any leading assistant turns — e.g. a
synthetic nudge-display opener — are dropped before the API call, since a conversation
sent to the model must start with a user turn.  ``memory_block`` (see
:mod:`wearable_insights.memory`) is folded into the grounding preamble when non-empty.
"""

from __future__ import annotations

from ..config import ANTHROPIC_API_KEY, CHAT_MODEL, MODEL_OPTIONS
from ..models import ComparisonObject, Nudge, NudgeSet
from .google_client import make_google_client
from .prompt import CHAT_SYSTEM_TEXT, build_chat_context, build_day_context
from .tools import TOOLS, execute_tool

_MAX_CHAT_TOKENS = 1024
_MAX_TOOL_ROUNDS = 5


def chat_reply(
    history: list[dict],
    comparison: ComparisonObject,
    *,
    nudge: Nudge | None = None,
    nudge_set: NudgeSet | None = None,
    memory_block: str = "",
    model: str | None = None,
    profile_dict: dict | None = None,
) -> str:
    """Generate the next assistant reply for an ongoing chat.

    Args:
        history:      All turns so far, latest user message last.  Leading
                      assistant turns (synthetic openers) are excluded from the call.
        comparison:   The day's ComparisonObject (grounding source).
        nudge:        If given, anchor the chat to this nudge; otherwise free chat.
        nudge_set:    Day's nudges, surfaced as context in free chats.
        memory_block: Carried-forward memory text; injected when non-empty.
        model:        Model ID from ``MODEL_OPTIONS``; defaults to ``CHAT_MODEL``.
        profile_dict: Raw profile dict (with ``records`` list).  Required for the
                      ``get_wearable_period_summary`` tool; if omitted, tool calls
                      will return empty period data.

    Returns:
        The assistant reply as a plain string.

    Raises:
        RuntimeError: if the required API key is not set.
        ValueError:   if the model is unknown.
    """
    resolved = model or CHAT_MODEL
    info = MODEL_OPTIONS.get(resolved)
    if info is None:
        raise ValueError(
            f"Unknown model '{resolved}'. Valid options: {list(MODEL_OPTIONS)}"
        )

    if nudge is not None:
        context = build_chat_context(nudge, comparison)
    else:
        context = build_day_context(comparison, nudge_set)

    if memory_block:
        context = f"{memory_block}\n\n{context}"

    # Drop any leading assistant turns (e.g. a synthetic nudge-display opener); the
    # API requires the real conversation to start with a user message.
    real_turns = list(history)
    while real_turns and real_turns[0]["role"] != "user":
        real_turns.pop(0)

    provider = info["provider"]
    if provider == "anthropic":
        return _anthropic_reply(context, real_turns, resolved, comparison, profile_dict or {})
    if provider == "google":
        return _google_reply(context, real_turns, resolved)
    raise ValueError(f"Unsupported provider '{provider}' for model '{resolved}'")


# ── Anthropic ─────────────────────────────────────────────────────────────────


def _anthropic_reply(
    context: str,
    real_turns: list[dict],
    model: str,
    comparison: ComparisonObject,
    profile_dict: dict,
) -> str:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. "
            "Export it in your environment to use the chatbot."
        )
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Inject grounding context as a synthetic preamble exchange so the LLM
    # treats it as established ground truth before the real conversation.
    messages: list[dict] = [
        {
            "role": "user",
            "content": f"<grounding>\n{context}\n</grounding>",
        },
        {
            "role": "assistant",
            "content": (
                "I've reviewed the data and what I remember about you. "
                "I'm ready to discuss this with you."
            ),
        },
        *real_turns,
    ]

    # Agentic tool-use loop: the model may call get_wearable_period_summary
    # one or more times before producing its final text reply.
    for _ in range(_MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=model,
            max_tokens=_MAX_CHAT_TOKENS,
            system=CHAT_SYSTEM_TEXT,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            # Normal end — extract and return the text block.
            for block in response.content:
                if block.type == "text":
                    return block.text
            return ""

        # Execute every tool call in this round and collect results.
        tool_results: list[dict] = []
        for block in response.content:
            if block.type == "tool_use":
                result_str = execute_tool(
                    block.name, block.input, comparison, profile_dict
                )
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_str,
                    }
                )

        # Append the assistant's tool-use turn and the tool results, then loop.
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    # Safety net: ask the model to reply without tools after too many rounds.
    response = client.messages.create(
        model=model,
        max_tokens=_MAX_CHAT_TOKENS,
        system=CHAT_SYSTEM_TEXT,
        messages=messages,
    )
    for block in response.content:
        if block.type == "text":
            return block.text
    return ""


# ── Google ────────────────────────────────────────────────────────────────────


def _google_reply(context: str, real_turns: list[dict], model: str) -> str:
    from google.genai import types

    client = make_google_client()

    # Google uses "user"/"model" roles.
    contents: list[dict] = [
        {"role": "user", "parts": [{"text": f"<grounding>\n{context}\n</grounding>"}]},
        {"role": "model", "parts": [{"text": "I've reviewed the data. Ready to help."}]},
    ]
    for turn in real_turns:
        role = "model" if turn["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": turn["content"]}]})

    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=CHAT_SYSTEM_TEXT,
            max_output_tokens=_MAX_CHAT_TOKENS,
        ),
    )
    return response.text or ""
