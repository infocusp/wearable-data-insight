# Implementation Plan: Anomaly Nudges & Insight Chatbot (Phase 2)

**Branch**: `002-nudges-chatbot` | **Date**: 2026-06-22 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-nudges-chatbot/spec.md`

## Summary

Extend the Phase 1 engine with two experience-layer changes, reusing the deterministic
analysis stack and the hybrid-insight contract unchanged:

1. **Event-driven nudges replace manual generation.** A new deterministic
   `anomaly.py` reads the existing `ComparisonObject` (trend labels, `evaluation_tag`s,
   flags) and emits a typed list of `Anomaly` records. A `nudges.py` orchestrator
   consolidates/prioritizes them into at most N (default 3) **Nudge** items, each wrapping
   a Phase 1 `Insight` produced by the same `llm/insight.py` + Claude path. A clean day
   yields zero nudges. Anomaly detection is pure Python and golden-tested; the LLM still
   only interprets — it never decides what is anomalous.
2. **A nudge-scoped chatbot.** A new `llm/chat.py` runs a multi-turn conversation grounded
   **only** in a selected nudge, its insight, and that day's `ComparisonObject`. A
   dedicated chat system prompt + a reused/extended `safety.py` gate keep every reply
   associative, non-diagnostic, nudge-scoped, and disclaimer-bearing; replies that violate
   the rules are regenerated, never surfaced raw. Chat state is in-memory and
   session-scoped (no persistence).

The Streamlit `app.py` gains a **nudge feed** (clickable cards → chat panel) and an
"all steady" empty state, keeping the Phase 1 trend cards and "generated from"
explainability. No new LLM provider, no database.

## Technical Context

**Language/Version**: Python 3.11+ (unchanged from Phase 1).

**Primary Dependencies**: Reuses Phase 1 stack — `anthropic` SDK (chat via
`messages.create` streaming for follow-ups; nudge insights still via
`messages.parse(InsightSet)` with adaptive thinking), `pydantic` v2 (new `Anomaly`,
`Nudge`, `ChatTurn`/`ChatSession` models), `streamlit` (nudge feed + chat panel using
`st.chat_message`/`st.chat_input` and `st.session_state`), `pytest`, `ruff`, `jsonschema`.
No new third-party dependency is introduced.

**Storage**: N/A — remains stateless and single-pass. Nudges are derived per run; chat
history lives only in Streamlit `session_state` for the open session and is discarded on
reset. The `ComparisonObject` may still be dumped to JSON for inspection.

**Testing**: `pytest`. New deterministic golden tests for `anomaly.py` (exact anomalies
per fixture day) and `nudges.py` (consolidation/cap, zero-on-clean-day). Chat tested with
a stubbed Anthropic client: grounding (no fabricated metrics), safety refusals
(diagnosis/medication/ER/jailbreak), and disclaimer presence — no live key required. A
small optional `-m live` smoke test exercises a real chat turn.

**Target Platform**: Local developer machine (Linux/macOS); Python + Streamlit app
(primary demo surface). Optional FastAPI service reuses the same nudge/chat engine.

**Performance Goals**: Interactive — a follow-up chat reply returns in under ~10 s
excluding model cold start (SC-009); deterministic anomaly + nudge selection is sub-second
on a 90-day history.

**Constraints**: Anomaly detection is deterministic and reproducible per seed/config
(SC-006); the LLM never computes or decides anomalies (Principle I); all nudge and chat
output is associative/non-diagnostic and schema-/safety-valid before it reaches the user
(Principle II/III); chat grounded strictly in the supplied nudge context (no fabrication);
`ANTHROPIC_API_KEY` from env, never committed/logged; deterministic suite passes without a
key.

**Scale/Scope**: Single user/day at a time; ≤ 3 nudges per day; one open chat session.
~4 new source modules (`anomaly.py`, `nudges.py`, `llm/chat.py`, chat-prompt additions) +
app changes; not a high-throughput service.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| # | Principle | How this plan satisfies it | Status |
|---|-----------|----------------------------|--------|
| I | Deterministic Analysis Before Inference | `anomaly.py` detects anomalies and `nudges.py` consolidates/caps them in pure Python from the existing `ComparisonObject`; the LLM only interprets (nudge insight) and converses — it never decides what is anomalous or computes numbers. Golden tests assert exact anomalies per seed (FR-002, FR-004, FR-021, SC-006). | PASS |
| II | Associative, Never Diagnostic (NON-NEGOTIABLE) | Nudges reuse the Phase 1 insight contract + `safety.py`; the chatbot adds a dedicated non-diagnostic system prompt and runs every reply through the safety gate (refuse diagnosis/medication/ER/jailbreak), disclaimer on every nudge and chat surface (FR-013–FR-017, SC-003, SC-005). | PASS |
| III | Contract-First Structured Data | New `Anomaly`, `Nudge`, and chat models have JSON Schemas in `contracts/`; nudge insights stay under `messages.parse`; chat replies are validated/filtered before display, never surfaced raw (FR-003, FR-017). | PASS |
| IV | Independently-Testable Vertical Slices | Stories P1–P4 are additive, standalone increments; P1 (auto nudges) is a viable MVP without the chat; chat (P2/P3) and dashboard feed (P4) layer on without breaking P1. | PASS |
| V | Explainability & Provenance | Each `Nudge` records the triggering anomalies/signals; the chat explains "why raised" only from those signals; the dashboard keeps the "generated from" view; `ComparisonObject` remains inspectable (FR-007, FR-009, FR-020, SC-004, SC-007). | PASS |
| VI | Reproducibility & Privacy by Default | Anomaly detection is seed-reproducible; synthetic/CSV only (no PHI); no new persistence; key from env (FR-021, FR-022, SC-006). | PASS |

**Technology constraints**: Python 3.11+, Claude via `anthropic` SDK (default
`claude-sonnet-4-6`, configurable) for both nudge insight and chat — no new provider;
stateless single-pass; Streamlit primary surface; optional FastAPI reuses the same engine.
All consistent with the constitution's Technology & Architecture Constraints. The
chatbot is a *new conversational surface* but stays within the existing
associative/non-diagnostic and contract-first rules — no principle is relaxed.

**Result**: Constitution Check PASSES. No entries required in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/002-nudges-chatbot/
├── spec.md              # Feature spec (input)
├── plan.md              # This file
├── research.md          # Phase 0 — decisions & rationale
├── data-model.md        # Phase 1 — new entities & schemas (Anomaly, Nudge, ChatSession)
├── quickstart.md        # Phase 1 — setup & run (nudge feed + chat)
├── contracts/           # Phase 1 — JSON Schemas for the new entities
│   ├── anomaly.schema.json
│   ├── nudge.schema.json
│   └── chat_message.schema.json
├── checklists/
│   └── requirements.md  # spec quality checklist (from /speckit-specify)
└── tasks.md             # produced by /speckit-tasks
```

### Source Code (repository root)

```text
src/wearable_insights/
├── config.py                 # +anomaly thresholds, MAX_NUDGES_PER_DAY (default 3), chat model id
├── models.py                 # +Anomaly, +Nudge, +NudgeSet, +ChatTurn, +ChatSession (Pydantic v2)
├── anomaly.py                # NEW — ComparisonObject → Anomaly[] via deterministic rules (FR-002, FR-021)
├── nudges.py                 # NEW — Anomaly[] → consolidated/prioritized Nudge[] (cap N); wraps llm/insight (FR-001,3,5,6,7)
├── safety.py                 # +check_chat_reply(): non-diagnostic / nudge-scoped / disclaimer gate (FR-013–FR-017)
├── pipeline.py               # auto-nudge path: snapshot → comparison → anomalies → nudges (replaces manual generate, FR-001)
├── llm/
│   ├── prompt.py             # +CHAT_SYSTEM_TEXT + build_chat_context(nudge, comparison) (FR-009, FR-010, FR-013)
│   ├── insight.py            # reused unchanged for per-nudge insight generation (FR-004)
│   └── chat.py               # NEW — multi-turn chat grounded in a Nudge; safety-gated replies (FR-008–FR-012)
├── app.py                    # nudge feed (clickable cards), chat panel, "all steady" empty state (FR-018–FR-020)
└── api.py                    # (optional) +/nudges, +/chat reusing the same engine

tests/
├── fixtures/                 # +golden anomalies/nudges per day; +stubbed chat transcripts
├── unit/
│   ├── test_anomaly.py       # NEW — exact anomalies per fixture; clean day → none (SC-002, SC-006)
│   ├── test_nudges.py        # NEW — consolidation, cap=3, zero-on-clean (FR-005, FR-006, SC-008)
│   ├── test_safety_chat.py   # NEW — reply gate: diagnosis/med/ER/jailbreak refusals (SC-003, SC-005)
│   └── test_chat_prompt.py   # NEW — chat context builder includes only nudge/comparison signals
├── contract/
│   ├── test_anomaly_schema.py    # NEW
│   ├── test_nudge_schema.py      # NEW
│   └── test_chat_message_schema.py # NEW
└── integration/
    ├── test_nudges_pipeline_p1.py  # NEW — end-to-end auto-nudge with stubbed LLM (SC-001)
    └── test_chat_session.py        # NEW — multi-turn grounding + refusal with stubbed LLM (SC-004, SC-005)
```

**Structure Decision**: Single-project layout, additive to Phase 1. The new deterministic
logic (`anomaly.py`, `nudges.py`) sits alongside the existing analytics modules and
consumes the unchanged `ComparisonObject`; the new conversational logic (`llm/chat.py`,
chat additions to `prompt.py`/`safety.py`) sits alongside the existing LLM boundary and
reuses `llm/insight.py` for per-nudge insights. `app.py` and the optional `api.py` remain
thin presentation layers over `pipeline.py`/`nudges.py`/`chat.py`, so each surface reuses
one engine (Constitution: optional API "MUST reuse the same … modules, not duplicate
them"). Design-time JSON Schemas for the new entities live in `contracts/`; runtime
validation uses the Pydantic mirrors in `models.py`, with contract tests keeping them in
sync.

## Complexity Tracking

> No Constitution Check violations — this section is intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
