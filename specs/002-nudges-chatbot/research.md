# Phase 0 Research: Anomaly Nudges & Insight Chatbot (Phase 2)

**Feature**: `002-nudges-chatbot` | **Date**: 2026-06-22

This phase resolves the design unknowns surfaced by the spec and Technical Context. Every
decision stays inside the existing constitution (deterministic-before-inference,
associative-never-diagnostic, contract-first, stateless) and reuses Phase 1 artifacts.

## D1 — How are anomalies detected?

- **Decision**: Add a pure-Python `anomaly.py` that reads the existing `ComparisonObject`
  and emits typed `Anomaly` records from a small, declarative rule table over the
  already-computed `trend`, `evaluation_tag`, and `flags` fields. Default rule set:
  `stress_elevated` (heart_health.stress trend `up` / tag `Significantly|Critically
  Elevated`), `steps_low` & `active_minutes_low` (activity down), `sleep_insufficient`
  (sleep_duration or sleep_score down / below-threshold flag), `hrv_depressed`
  (heart_health.hrv down). Each anomaly carries `severity` derived from the
  evaluation_tag (`critical` > `significant` > `moderate`).
- **Rationale**: The comparison object already encodes deviation magnitude and direction
  deterministically (Phase 1 FR-008/FR-009); detecting anomalies is a thin, testable
  classification on top — no new math, no LLM involvement (Principle I). A declarative
  rule table mirrors the existing `associations.py` pattern and is extensible without
  reshaping the engine.
- **Alternatives considered**: (a) Let the LLM decide what is anomalous — rejected, violates
  Principle I and reproducibility. (b) Recompute thresholds from raw records in
  `anomaly.py` — rejected, duplicates Phase 1 logic and risks divergence; reuse the
  comparison object instead.

## D2 — How are multiple anomalies consolidated into nudges?

- **Decision**: `nudges.py` groups anomalies by theme (sleep / recovery / activity /
  stress), orders groups by max severity, and produces at most `MAX_NUDGES_PER_DAY`
  (default 3, configurable) nudges. Related anomalies that share a fired
  `candidate_association` (e.g. sleep↓ & stress↑) are folded into one nudge so the
  narrative connects them; overflow lower-severity anomalies are summarized inside an
  existing nudge rather than dropped silently.
- **Rationale**: Satisfies FR-006/SC-008 (no flooding) while preserving explainability —
  every nudge still lists its triggering signals. Reusing the Phase 1 associations keeps
  the "connect the dots" behavior without new causal logic.
- **Alternatives considered**: One nudge per anomaly (rejected — floods the user on bad
  days); a single mega-nudge (rejected — loses the one-action-per-insight focus and
  per-theme clarity).

## D3 — One LLM insight per nudge, or one InsightSet split into nudges?

- **Decision**: Generate a per-nudge `Insight` by calling the **existing** `llm/insight.py`
  path with a comparison object focused on that nudge's theme/signals, keeping the Phase 1
  `messages.parse(InsightSet)` contract and `safety.py` gate. A `Nudge` wraps exactly one
  `Insight` (one action, per Principle II).
- **Rationale**: Maximum reuse of the validated Phase 1 generation + safety path (FR-004);
  one nudge = one insight = one action keeps the existing safety invariants intact.
- **Alternatives considered**: A brand-new multi-nudge generation prompt — rejected,
  duplicates the insight contract and the safety surface for no benefit.

## D4 — Chatbot grounding and turn protocol

- **Decision**: `llm/chat.py` builds each request from a `CHAT_SYSTEM_TEXT` (role: a
  wellness explainer, explicitly *not a doctor*, scoped to one nudge) plus a
  `build_chat_context(nudge, comparison)` block containing only that nudge's insight, its
  triggering signals, and the day's comparison object. Prior turns are replayed from the
  in-memory `ChatSession`. Replies use `messages.create` (streamed for UX); free-text, not
  `messages.parse`, because the output is conversational prose.
- **Rationale**: Strict grounding (FR-009/FR-012/SC-004) — the model can only reference
  what it is given, so it cannot fabricate metrics or other days. Reusing the comparison
  object as the sole data source keeps Principle I intact (no recomputation requested).
- **Alternatives considered**: Tool/function calling to fetch metrics on demand — rejected
  as over-engineering for a stateless single-day PoC; RAG over a knowledge base —
  explicitly out of scope (deferred to a later phase per the constitution).

## D5 — Chat safety enforcement

- **Decision**: Extend `safety.py` with `check_chat_reply(text, comparison)` reusing the
  existing banned diagnostic/causal lexicon plus chat-specific rules: refuse
  diagnosis/medication/dosage/ER framing, stay nudge-scoped, require the disclaimer on the
  chat surface. The system prompt instructs the model to *refuse and redirect*; the
  post-generation gate is the backstop — a failing reply is regenerated once with a
  corrective instruction, and if it still fails a safe canned fallback is shown. User
  jailbreak attempts cannot relax the system prompt or the gate.
- **Rationale**: Defense in depth mirroring Phase 1 (prompt + post-gate, FR-013–FR-017,
  SC-003/SC-005); reuses the audited lexicon so nudges and chat share one safety
  definition.
- **Alternatives considered**: Prompt-only safety — rejected, the constitution requires a
  validating gate that never surfaces raw output (Principle III).

## D6 — Chat state & persistence

- **Decision**: Keep Phase 2 stateless. Chat history lives in Streamlit `st.session_state`
  keyed by nudge id for the open session and is discarded on rerun/reset; nothing is
  written to disk or a database. The optional FastAPI surface, if built, passes prior turns
  explicitly in the request (the client holds session state).
- **Rationale**: Honors the spec's stateless assumption and the constitution's "no database
  in Phase 1/2" posture; avoids PHI-at-rest concerns (Principle VI).
- **Alternatives considered**: Persisting transcripts for longitudinal context — rejected,
  out of scope and a privacy surface; deferred.

## D7 — Streamlit interaction model for the nudge feed + chat

- **Decision**: Render nudges as cards in the existing dashboard; a card's button sets the
  active nudge id in `session_state` and reveals a chat panel built with
  `st.chat_message` / `st.chat_input`. A clean day shows an "all steady" empty state and no
  chat. The Phase 1 trend cards and "generated from" explainability remain.
- **Rationale**: Uses Streamlit-native chat primitives (no new dependency), keeps one demo
  surface, satisfies FR-018–FR-020.
- **Alternatives considered**: A separate chat page/route — rejected as heavier than needed
  for a single-screen demo.

## Resolved unknowns

All Technical Context items are resolved; no `NEEDS CLARIFICATION` markers remain. Open
*tuning* values (exact anomaly thresholds, nudge cap) are configurable in `config.py` with
documented defaults and do not block design.
