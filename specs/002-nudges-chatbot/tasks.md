---
description: "Task list for 002-nudges-chatbot implementation"
---

# Tasks: Anomaly Nudges & Insight Chatbot (Phase 2)

**Input**: Design documents from `/specs/002-nudges-chatbot/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: INCLUDED — the constitution mandates golden tests for deterministic layers,
schema/contract validation, and safety checks (see `.specify/memory/constitution.md`
Quality Gates), so test tasks are first-class here.

**Organization**: Tasks are grouped by user story (US1–US4 from spec.md) for independent
implementation and testing. This feature is **additive** to the Phase 1 engine
(`001-wearable-insights`); reused modules are not rebuilt.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1, US2, US3, US4
- Paths are repository-relative; single-project layout (`src/wearable_insights/`, `tests/`)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Configuration and fixtures the new modules depend on

- [ ] T001 Add Phase 2 settings to [src/wearable_insights/config.py](../../src/wearable_insights/config.py): `MAX_NUDGES_PER_DAY` (default 3), anomaly threshold knobs, and the chat model id (defaulting to the existing `WEARABLE_MODEL`)
- [ ] T002 [P] Create golden fixtures dir `tests/fixtures/phase2/` with an anomaly-rich day (recovery-deficit) and a clean (all-stable) day comparison-object JSON, plus stubbed chat transcript fixtures
- [ ] T003 [P] Verify `ruff` + `pytest` config already cover the new `anomaly.py`/`nudges.py`/`llm/chat.py` paths (no new tooling) in [pyproject.toml](../../pyproject.toml)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: New Pydantic models + contract tests that every story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T004 [P] Add `Anomaly` model (code/theme/severity/signals/evaluation_tag/detail enums) to [src/wearable_insights/models.py](../../src/wearable_insights/models.py) per [data-model.md](./data-model.md)
- [ ] T005 [P] Add `Nudge` and `NudgeSet` models (cap enforced via validator) to [src/wearable_insights/models.py](../../src/wearable_insights/models.py)
- [ ] T006 [P] Add `ChatTurn` and `ChatSession` models (grounding = nudge + comparison) to [src/wearable_insights/models.py](../../src/wearable_insights/models.py)
- [ ] T007 [P] Contract test: validate `Anomaly` Pydantic ↔ schema in tests/contract/test_anomaly_schema.py against [contracts/anomaly.schema.json](./contracts/anomaly.schema.json)
- [ ] T008 [P] Contract test: validate `NudgeSet` ↔ schema in tests/contract/test_nudge_schema.py against [contracts/nudge.schema.json](./contracts/nudge.schema.json)
- [ ] T009 [P] Contract test: validate `ChatSession` ↔ schema in tests/contract/test_chat_message_schema.py against [contracts/chat_message.schema.json](./contracts/chat_message.schema.json)

**Checkpoint**: Models + contracts in place — user stories can begin

---

## Phase 3: User Story 1 - Automatic anomaly nudges replace manual generation (Priority: P1) 🎯 MVP

**Goal**: Processing a day automatically raises bounded, schema-valid nudges from detected
anomalies (no manual trigger); a clean day raises none.

**Independent Test**: Run the auto-nudge pipeline on the recovery-deficit day → ≥1 nudge,
each wrapping a valid Insight (one action, disclaimer, triggered_by signals); run on an
all-stable day → empty NudgeSet.

### Tests for User Story 1 ⚠️ (write first, ensure they fail)

- [ ] T010 [P] [US1] Golden test for anomaly detection in tests/unit/test_anomaly.py: exact `Anomaly[]` for the recovery-deficit fixture; empty for the clean-day fixture (SC-002, SC-006)
- [ ] T011 [P] [US1] Unit test for nudge consolidation in tests/unit/test_nudges.py: grouping by theme, cap = `MAX_NUDGES_PER_DAY`, zero-on-clean-day (FR-005, FR-006, SC-008)
- [ ] T012 [P] [US1] Integration test in tests/integration/test_nudges_pipeline_p1.py: snapshot → comparison → anomalies → NudgeSet end-to-end with the stubbed LLM client (SC-001)

### Implementation for User Story 1

- [ ] T013 [US1] Implement deterministic anomaly detection in src/wearable_insights/anomaly.py: `detect_anomalies(ComparisonObject) -> list[Anomaly]` via a declarative rule table over trend/evaluation_tag/flags (FR-002, FR-021) — see [research.md](./research.md) D1
- [ ] T014 [US1] Implement nudge consolidation in src/wearable_insights/nudges.py: group anomalies by theme, prioritize by severity, fold association-linked anomalies, cap at `MAX_NUDGES_PER_DAY` (FR-006) — research D2
- [ ] T015 [US1] In src/wearable_insights/nudges.py, build a per-nudge `Insight` by reusing [llm/insight.py](../../src/wearable_insights/llm/insight.py) on a theme-focused comparison view, then assemble `Nudge`/`NudgeSet` (FR-003, FR-004, FR-007) — research D3
- [ ] T016 [US1] Wire the auto-nudge path into [src/wearable_insights/pipeline.py](../../src/wearable_insights/pipeline.py) and REMOVE the manual "generate insights" trigger (FR-001, FR-005)
- [ ] T017 [US1] Run each nudge's insight through the existing [safety.py](../../src/wearable_insights/safety.py) gate; reject/retry invalid output, never surface raw (FR-016-equivalent, SC-003)

**Checkpoint**: US1 is a functional MVP — proactive nudges with zero manual steps

---

## Phase 4: User Story 2 - Chat with the bot about a nudge (Priority: P2)

**Goal**: Clicking a nudge opens a multi-turn chat grounded only in that nudge + the day's
comparison object; answers explain "why" and discuss the action without fabricating data.

**Independent Test**: Open a chat for a generated nudge, ask "why was this raised?" → reply
uses only that day's triggering signals; ask about absent data → bot redirects.

### Tests for User Story 2 ⚠️

- [ ] T018 [P] [US2] Unit test for chat context builder in tests/unit/test_chat_prompt.py: `build_chat_context` includes only the nudge's insight + comparison signals, no extras (FR-009)
- [ ] T019 [P] [US2] Integration test in tests/integration/test_chat_session.py: multi-turn session with stubbed client — grounded "why" answer + out-of-scope redirect (FR-012, SC-004)

### Implementation for User Story 2

- [ ] T020 [US2] Add `CHAT_SYSTEM_TEXT` and `build_chat_context(nudge, comparison)` to [src/wearable_insights/llm/prompt.py](../../src/wearable_insights/llm/prompt.py) (FR-009, FR-010) — research D4
- [ ] T021 [US2] Implement src/wearable_insights/llm/chat.py: `reply(session, user_message) -> str` replaying `ChatSession.turns`, calling Claude via `messages.create` (streamed), grounded in the context block (FR-008, FR-011)
- [ ] T022 [US2] Implement out-of-scope redirection so questions beyond the grounding are deflected, not fabricated (FR-012)

**Checkpoint**: US1 + US2 work — nudges are clickable and conversational

---

## Phase 5: User Story 3 - Chatbot stays non-diagnostic and safe (Priority: P3)

**Goal**: Every chat reply is associative, non-diagnostic, nudge-scoped, disclaimer-bearing;
diagnosis/medication/ER/jailbreak prompts are refused/redirected, never surfaced raw.

**Independent Test**: Send probing prompts (diagnosis, "do I have X?", dosage, ER,
"act as my doctor") → all refuse/redirect with disclaimer.

### Tests for User Story 3 ⚠️

- [ ] T023 [P] [US3] Unit test in tests/unit/test_safety_chat.py: `check_chat_reply` flags diagnostic/causal/clinical replies and passes clean ones (SC-003)
- [ ] T024 [P] [US3] Integration test in tests/integration/test_chat_session.py (extend): probing/jailbreak prompts → refusal/redirect + safe fallback when regeneration still fails (SC-005)

### Implementation for User Story 3

- [ ] T025 [US3] Add `check_chat_reply(text, comparison)` to [src/wearable_insights/safety.py](../../src/wearable_insights/safety.py) reusing the banned diagnostic/causal lexicon + chat rules (refuse clinical, require disclaimer) (FR-013, FR-014, FR-016) — research D5
- [ ] T026 [US3] In src/wearable_insights/llm/chat.py, gate every assistant turn through `check_chat_reply`: regenerate once with a corrective instruction, else show a safe canned fallback (FR-015, FR-017)
- [ ] T027 [US3] Harden `CHAT_SYSTEM_TEXT` against role-override/jailbreak ("not a doctor", non-overridable) in [src/wearable_insights/llm/prompt.py](../../src/wearable_insights/llm/prompt.py) (FR-015)

**Checkpoint**: Chat carries the same safety guarantees as one-shot insights

---

## Phase 6: User Story 4 - Nudge feed on the dashboard (Priority: P4)

**Goal**: Dashboard shows a clickable nudge feed (capped) with trend cards and "generated
from" explainability; clicking opens the chat panel; a clean day shows "all steady".

**Independent Test**: Load a day with anomalies → ≤3 nudge cards + chat on click + trend
cards + disclaimer; load a clean day → empty "all steady" state, no chat.

### Tests for User Story 4 ⚠️

- [ ] T028 [P] [US4] Smoke/render test for the nudge-feed + empty-state logic in tests/unit/test_app_nudge_feed.py (helper functions, stubbed engine) (FR-019)

### Implementation for User Story 4

- [ ] T029 [US4] Render the nudge feed (one card per nudge: title, summary, single action) capped at `MAX_NUDGES_PER_DAY` in [src/wearable_insights/app.py](../../src/wearable_insights/app.py) (FR-018, SC-008)
- [ ] T030 [US4] Add the chat panel using `st.chat_message`/`st.chat_input` + `st.session_state` keyed by nudge id; clicking a card opens it; nothing persists across sessions (FR-008, FR-011)
- [ ] T031 [US4] Add the "all steady" empty state for clean days and keep the Phase 1 trend cards + "generated from" explainability linking each nudge to its `triggered_by` signals (FR-019, FR-020, SC-007)
- [ ] T032 [US4] Ensure the informational-only disclaimer is visible on the nudge feed and the chat surface (FR-016)

**Checkpoint**: All four stories independently functional

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T033 [P] (Optional) Add `/nudges` and `/chat` endpoints to [src/wearable_insights/api.py](../../src/wearable_insights/api.py) reusing nudges.py/chat.py (FR — optional API parity)
- [ ] T034 [P] Update [README.md](../../README.md) and the Phase-2 quickstart references for the nudge feed + chat
- [ ] T035 Run [quickstart.md](./quickstart.md) Scenarios 1–4 end-to-end (stubbed + one `-m live` smoke turn)
- [ ] T036 Run full gate: `pytest` and `ruff check . && ruff format --check .`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies — start immediately
- **Foundational (Phase 2)**: depends on Setup — **BLOCKS all user stories**
- **User Stories (Phase 3–6)**: all depend on Foundational
  - US1 (P1) is the MVP and should land first
  - US2 (P2) depends on US1 (needs a Nudge to chat about)
  - US3 (P3) depends on US2 (gates the chat replies US2 produces)
  - US4 (P4) depends on US1 (feed) and surfaces US2/US3 chat
- **Polish (Phase 7)**: after the desired stories are complete

### Within Each User Story

- Tests written first and failing, then models → services → surface
- US1: anomaly.py → nudges.py → pipeline wiring → safety gate
- US2: prompt context → chat.py → redirection
- US3: safety.check_chat_reply → chat gating → prompt hardening
- US4: feed render → chat panel → empty state/explainability → disclaimer

### Parallel Opportunities

- Setup: T002, T003 in parallel
- Foundational: T004–T009 all `[P]` (distinct concerns; T004–T006 touch models.py — coordinate if same file, otherwise sequence them)
- US1 tests T010–T012 in parallel; US2 tests T018–T019; US3 tests T023–T024
- Across teams: once Foundational is done, US1 unblocks US2→US3 (sequential due to chat dependency) while US4's feed (T029) can start in parallel with US2 once US1 nudges exist

---

## Parallel Example: User Story 1

```bash
# Tests first (parallel):
Task: "Golden test for anomaly detection in tests/unit/test_anomaly.py"
Task: "Unit test for nudge consolidation in tests/unit/test_nudges.py"
Task: "Integration test in tests/integration/test_nudges_pipeline_p1.py"

# Then implementation (anomaly.py and nudges.py are different files):
Task: "Implement detect_anomalies in src/wearable_insights/anomaly.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup → Phase 2 Foundational (models + contracts)
2. Phase 3 US1: deterministic anomalies + bounded nudges replacing manual generation
3. **STOP & VALIDATE**: recovery-deficit day raises nudges; clean day raises none
4. Demo the proactive-nudge behavior — the core Phase 2 promise

### Incremental Delivery

1. Foundation → US1 (MVP: auto nudges) → demo
2. US2 (chat about a nudge) → demo
3. US3 (chat safety guarantees) → demo
4. US4 (dashboard nudge feed + chat panel) → demo
5. Polish (optional API, docs, quickstart validation)

---

## Notes

- `[P]` = different files, no incomplete-task dependency
- Reused unchanged from Phase 1: `comparison.py`, `associations.py`, `llm/insight.py`,
  `llm/prompt.py` (insight portion), the `Insight`/`ComparisonObject` contracts
- Deterministic suite (anomaly + nudge + chat-safety gate) MUST pass without an API key
- Commit after each task or logical group; stop at any checkpoint to validate independently
