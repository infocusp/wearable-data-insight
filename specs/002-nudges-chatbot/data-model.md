# Phase 2 Data Model: Anomaly Nudges & Insight Chatbot

**Feature**: `002-nudges-chatbot` | **Date**: 2026-06-22

New entities are implemented as Pydantic v2 models added to
`src/wearable_insights/models.py`. JSON Schemas in `contracts/` are the design-time source
of truth; contract tests assert the Pydantic models and the schemas stay in sync. All
Phase 1 entities (`CanonicalDailyRecord`, `BaselineSet`, `ComparisonObject`,
`CandidateAssociation`, `Insight`, `InsightSet`) are **reused unchanged** — see
`specs/001-wearable-insights/data-model.md`.

## Entity: Anomaly

A deterministically detected deviation for one day, derived from the `ComparisonObject`
(FR-002, FR-021). Pure data — produced by `anomaly.py`, never by the LLM.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `code` | enum | yes | `stress_elevated` \| `steps_low` \| `active_minutes_low` \| `sleep_insufficient` \| `sleep_quality_low` \| `hrv_depressed` (extensible) |
| `theme` | enum | yes | `sleep` \| `recovery` \| `activity` \| `stress` — used for nudge grouping |
| `severity` | enum | yes | `moderate` \| `significant` \| `critical` — mapped from `evaluation_tag` |
| `signals` | string[] | yes | comparison signal keys that triggered it, e.g. `["stress"]` (provenance) |
| `evaluation_tag` | string | yes | copied from the triggering `MetricComparison` for traceability |
| `detail` | string | yes | short deterministic description, e.g. "stress 28% above 30-day baseline" |

**Rules**: `code` fires only when its rule matches the comparison object's `trend` /
`evaluation_tag` / `flags`; a metric that is `Stable / Within Normal Baseline` raises no
anomaly. `signals` ⊆ the keys present in the comparison object. Detection is reproducible
per seeded input (SC-006).

## Entity: Nudge

A user-facing item automatically raised from one or more anomalies, wrapping exactly one
Phase 1 `Insight` (FR-003, FR-007). The unit a user clicks to start a chat.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `nudge_id` | string | yes | stable per (user, date, theme), e.g. `usr_01_2026-06-20_recovery` |
| `user_id` | string | yes | |
| `analysis_date` | date | yes | |
| `theme` | enum | yes | `sleep` \| `recovery` \| `activity` \| `stress` |
| `severity` | enum | yes | max severity across its anomalies |
| `anomalies` | `Anomaly[]` | yes | one or more triggering anomalies (≥ 1) |
| `insight` | `Insight` | yes | the hybrid insight (title, narrative, one action, confidence, source_signals) |
| `disclaimer` | string | yes | informational-only disclaimer (FR-016) |
| `triggered_by` | string[] | yes | union of anomaly `signals` (explainability, SC-007) |

**Rules**: a `Nudge` always wraps exactly one `Insight` ending in exactly one action
(Principle II). `triggered_by` is the provenance shown in the "generated from" view.

## Entity: NudgeSet

The bounded result of processing one day (FR-005, FR-006).

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `user_id` | string | yes | |
| `analysis_date` | date | yes | |
| `nudges` | `Nudge[]` | yes | `0 .. MAX_NUDGES_PER_DAY` (default 3); **empty on a clean day** |
| `schema_version` | string | yes | e.g. `1.0` |

**Rules**: `len(nudges) ≤ MAX_NUDGES_PER_DAY` (SC-008); an all-within-baseline day yields
an empty list, never a fabricated nudge (FR-005, SC-002).

## Entity: ChatTurn

One message in a nudge-scoped conversation.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `role` | enum | yes | `user` \| `assistant` |
| `content` | string | yes | message text |

## Entity: ChatSession

In-memory, session-scoped conversation bound to one nudge (FR-008, FR-011). **Not
persisted** beyond the session (Principle VI).

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `nudge_id` | string | yes | the nudge this chat is grounded in |
| `turns` | `ChatTurn[]` | yes | ordered conversation history for the open session |
| `grounding` | object | yes | `{ nudge: Nudge, comparison: ComparisonObject }` — the only data the bot may reference (FR-009) |

**Rules**: the assistant may reference only signals present in `grounding`; questions
outside that scope are redirected, not fabricated (FR-012). Every assistant turn passes
`safety.check_chat_reply` before display (FR-013–FR-017); a failing reply is regenerated
or replaced with a safe fallback, never surfaced raw.

## Relationships

```text
ComparisonObject ──(anomaly.py)──> Anomaly[]
Anomaly[] ──(nudges.py: group + cap + llm/insight.py)──> NudgeSet ── Nudge ─1─> Insight
Nudge + ComparisonObject ──(llm/chat.py)──> ChatSession ──(turn)──> ChatTurn(assistant)
ChatTurn(assistant) ──(safety.check_chat_reply)──> validated reply (or safe fallback)
```

## State & lifecycle

Stateless and single-pass for generation: a run takes a `UserProfile` and an
`analysis_date`, flows snapshot → `ComparisonObject` → `Anomaly[]` → `NudgeSet`. Chat is
the only interactive part and holds state solely in memory for the open session: each user
turn appends to `ChatSession.turns`, the grounded request is sent to Claude, the reply is
safety-gated, appended, and rendered. Closing/resetting the session discards all turns;
nothing is written to disk or a database.
