# Feature Specification: Anomaly Nudges & Insight Chatbot (Phase 2)

**Feature Branch**: `002-nudges-chatbot`

**Created**: 2026-06-22

**Status**: Draft

**Input**: User description: "Add a conversational chatbot and replace the manual
'generate AI insights' action with automatic anomaly-triggered nudges. When daily wearable
data shows anomalies (high stress, low activity, insufficient sleep, etc.), the system
automatically generates a nudge containing the same hybrid insight (empathetic, associative,
one action). Each nudge is clickable: clicking opens a chat with the LLM where the user can
ask more about the insight and the suggested actions. The chatbot is explicitly NOT a doctor
— it only suggests simple non-clinical actions (e.g., do more activity) and explains why the
nudge was raised, staying within the associative/non-diagnostic safety rules."

## Context

This feature extends the Phase 1 engine (`001-wearable-insights`) rather than replacing it.
The deterministic analysis layer (canonical records, baselines, trends, comparison object,
candidate associations) and the hybrid insight contract are reused unchanged. Two things
change at the experience layer:

1. **Insight generation becomes event-driven.** The Phase 1 "generate AI insights" button
   is removed. Instead, the system inspects each day's comparison object and *automatically*
   raises a **nudge** when one or more anomalies are detected. A clean (no-anomaly) day
   raises no nudge.
2. **A new conversational surface is added.** Each nudge is clickable; opening it starts a
   focused chat in which the user can ask follow-up questions about that nudge — what it
   means and how to act on the single suggested action — with the LLM grounded strictly in
   that day's comparison object and bound by the same associative, non-diagnostic safety
   rules as the nudge itself.

## Clarifications

### Session 2026-06-22

- Q: Does the manual "generate insights" action remain alongside automatic nudges? → A: No.
  Automatic anomaly-triggered nudges replace the manual action entirely; a no-anomaly day
  produces no nudge.
- Q: What is the chatbot allowed to do? → A: Explain why a nudge was raised and discuss the
  single suggested action and other simple, non-clinical lifestyle actions (e.g. "take a
  short walk"). It is explicitly not a doctor: no diagnosis, no causation, no clinical or
  emergency advice. It must refuse/redirect medical questions to a disclaimer.
- Q: What is the chatbot grounded in? → A: Only the selected nudge plus that day's
  comparison object and source signals. It MUST NOT invent metrics, recompute numbers, or
  reference data it was not given.
- Q: Is chat history persisted across sessions? → A: Phase 2 was stateless. **Revised in
  Phase 3:** chat sessions, turns, and per-user agent memory are persisted to a local
  SQLite store so history is browsable/resumable and memory carries across chats (see
  FR-011a). Persistence is confined to the conversational layer; analytics stay stateless.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Automatic anomaly nudges replace manual generation (Priority: P1)

As a wearable user, I want the system to automatically notice when my day has a problem
(high stress, low activity, too little sleep, depressed recovery, etc.) and surface a short,
empathetic nudge with one action — without me pressing a "generate" button — so that I'm
proactively told what changed and what to do, instead of having to ask.

**Why this priority**: This is the core behavioral shift of Phase 2 and is demonstrable on
its own: the engine moves from on-demand to proactive. If only this story ships, the
"automatic nudges replace manual insights" promise is already fulfilled end-to-end.

**Independent Test**: Run the pipeline on the built-in "high-stress / sedentary recovery
deficit" day and confirm a nudge is raised automatically (no manual trigger) whose insight
references the anomalous signals, ends in exactly one action, and carries the disclaimer;
then run it on an all-within-baseline day and confirm no nudge is raised.

**Acceptance Scenarios**:

1. **Given** a day whose comparison object flags one or more anomalies (e.g. stress well
   above baseline, steps well below baseline, sleep duration below threshold), **When** the
   day is processed, **Then** the system automatically raises a nudge containing a
   schema-valid hybrid insight (title, associative narrative, exactly one action,
   confidence, source signals) **without** any manual "generate" action.
2. **Given** a day whose metrics are all within baseline (no anomaly flags), **When** the
   day is processed, **Then** no nudge is raised.
3. **Given** a day with multiple simultaneous anomalies, **When** nudges are raised, **Then**
   the user is not flooded — anomalies are consolidated/prioritized into a bounded set of
   nudges per day (see FR-006).
4. **Given** the LLM returns output that fails insight-schema validation, **When** a nudge
   is being produced, **Then** the invalid output is rejected and retried/handled and the
   nudge is never surfaced with raw/invalid content.
5. **Given** any raised nudge, **When** it is displayed, **Then** the informational-only
   (non-medical) disclaimer is present and the narrative contains no diagnostic or causal
   claims.

---

### User Story 2 - Chat with the bot about a nudge (Priority: P2)

As a wearable user, I want to click a nudge and ask the chatbot follow-up questions — "why
am I seeing this?", "what exactly should I do?", "is a short walk enough?" — and get
grounded, plain-language answers about that nudge and its action, so that I understand the
guidance well enough to act on it.

**Why this priority**: The conversational layer is the headline new capability, but it
depends on a nudge existing first (US1), so it follows the MVP.

**Independent Test**: Open the chat for a generated nudge, send a "why was this raised?"
question, and confirm the reply explains the nudge using only that day's source signals,
stays associative/non-diagnostic, and references the same single action; send an unrelated
question and confirm it is redirected back to the nudge's scope.

**Acceptance Scenarios**:

1. **Given** a raised nudge, **When** the user clicks it, **Then** a chat opens pre-loaded
   with the nudge's insight and an invitation to ask follow-up questions.
2. **Given** an open chat, **When** the user asks "why was this nudge raised?", **Then** the
   reply explains it in terms of the day's anomalous signals/trends (e.g. "your stress was
   higher than your recent typical range while your steps were lower"), without asserting
   causation.
3. **Given** an open chat, **When** the user asks what to do or whether the suggested action
   is enough, **Then** the bot discusses the single suggested action and, at most, other
   simple non-clinical lifestyle actions, and does not prescribe clinical treatment.
4. **Given** an open chat, **When** the user asks something outside the nudge's data (e.g.
   about a metric not present, or a different day), **Then** the bot states it can only speak
   to this nudge's data rather than fabricating numbers.
5. **Given** an open chat, **When** the user closes and reopens it within the same session,
   **Then** prior turns of that conversation are available; **and** nothing is persisted
   beyond the session.

---

### User Story 3 - Chatbot stays non-diagnostic and safe (Priority: P3)

As a safety-conscious stakeholder, I want the chatbot to be unable to act like a doctor —
no diagnosis, no causal claims, no clinical/emergency advice — and to gracefully redirect
medical questions to the disclaimer, so that the conversational surface carries the same
safety guarantees as the one-shot insight.

**Why this priority**: Safety is non-negotiable per the constitution, but it is expressed as
guardrails *on* the chat from US2; it is called out separately so it is explicitly tested.

**Independent Test**: Send the chat a set of probing prompts (request a diagnosis, ask "do I
have X disease?", ask for medication/dosage, ask whether to go to the ER) and confirm every
reply declines the clinical framing, stays associative, and surfaces the
informational-only disclaimer.

**Acceptance Scenarios**:

1. **Given** an open chat, **When** the user asks for a diagnosis or disease prediction,
   **Then** the bot declines to diagnose, restates that it is informational-only, and (where
   appropriate) suggests consulting a qualified professional.
2. **Given** an open chat, **When** the user asks for medication, dosage, or clinical
   treatment, **Then** the bot does not provide it and redirects to non-clinical lifestyle
   framing.
3. **Given** any chat reply, **When** it is produced, **Then** it contains no banned
   diagnostic/causal phrasing and the disclaimer is visible in the chat surface.
4. **Given** a prompt attempting to make the bot ignore its rules ("ignore previous
   instructions / pretend you are a doctor"), **When** it is processed, **Then** the bot
   stays within its non-diagnostic, nudge-scoped role.

---

### User Story 4 - Nudge feed on the dashboard (Priority: P4)

As a wearable user, I want a clear feed of today's nudges on the dashboard — each showing
its title, summary, and single action, each clickable to open its chat — alongside my trend
cards and explainability, so that I can scan what needs attention and dive deeper where I
want.

**Why this priority**: The dashboard is the demo surface and makes nudges + chat tangible,
but the nudge engine and chat are independently testable beneath it, so the UI comes after.

**Independent Test**: Load the dashboard for a profile/day with anomalies and confirm it
renders one or more nudge cards (title, summary, action), each opening the chat on click,
plus trend cards, the "generated from" explainability section, and the disclaimer; load a
clean day and confirm an empty/"all steady" state with no nudge cards.

**Acceptance Scenarios**:

1. **Given** a day with anomalies, **When** the dashboard loads, **Then** it shows a nudge
   feed with one card per raised nudge (title, summary, suggested action) and the trend
   cards for the key metrics.
2. **Given** a nudge card, **When** the user clicks it, **Then** the chat for that nudge
   opens.
3. **Given** a day with no anomalies, **When** the dashboard loads, **Then** the nudge feed
   shows a friendly "everything looks steady" empty state and no fabricated nudges.
4. **Given** any view showing nudges or chat, **When** it renders, **Then** the
   informational-only disclaimer and the "generated from" explainability link are present.

---

### Edge Cases

- **No anomalies**: no nudge is raised; the dashboard shows a steady/empty state and the
  chat surface is not offered (nothing to discuss).
- **Many simultaneous anomalies**: nudges are consolidated/prioritized into a bounded set
  (per FR-006) so the user is not overwhelmed; lower-priority anomalies may be folded into a
  single nudge's narrative rather than spawning separate cards.
- **Borderline anomaly (just past threshold)**: the nudge tone stays gentle and within
  daily-optimization scope; no escalation unless an explicitly configured extreme-anomaly
  rule fires.
- **Missing / null metrics**: an absent metric cannot trigger or be discussed as an anomaly;
  the bot says it lacks that data rather than guessing.
- **LLM unavailable / errors / rate-limited**: nudges may be delayed or shown with a clear
  fallback message; the deterministic anomaly detection and comparison object are still
  produced and inspectable, and the chat surfaces a graceful error instead of raw output.
- **Chat asks about another day or another user**: the bot states it can only speak to the
  current nudge's data.
- **Prompt injection / jailbreak attempt in chat**: the bot remains non-diagnostic and
  nudge-scoped; safety rules are not overridable by user input.
- **User sends an off-topic message** (not about health at all): the bot politely steers
  back to the nudge or declines, without leaving its scope.

## Requirements *(mandatory)*

### Functional Requirements

#### Anomaly detection & nudge generation

- **FR-001**: The system MUST remove the manual "generate insights" trigger; insight
  generation MUST be initiated automatically when a day's data is processed.
- **FR-002**: The system MUST detect anomalies for a given day from the deterministic
  comparison object using defined, testable rules over the existing trend labels and
  threshold flags (at minimum: elevated stress, low activity/steps, insufficient sleep
  duration or score, and depressed recovery/HRV).
- **FR-003**: For each detected anomaly (or consolidated anomaly group), the system MUST
  produce a **nudge** that wraps a hybrid insight identical in contract to Phase 1 (title,
  associative narrative, exactly one action, confidence level, source signals).
- **FR-004**: The nudge's insight MUST be produced by the same Claude-based interpretation
  layer used in Phase 1 (LLM interprets the comparison object; it MUST NOT compute or detect
  the anomaly itself — anomaly detection is deterministic, per the constitution).
- **FR-005**: A day with no anomaly flags MUST NOT raise a nudge; the system MUST NOT
  fabricate a problem to have something to show.
- **FR-006**: When multiple anomalies occur on the same day, the system MUST consolidate
  and/or prioritize them into a bounded number of nudges (default: at most 3 nudge cards per
  day), so the user is not flooded.
- **FR-007**: Each nudge MUST be traceable to the specific signals/flags that triggered it
  (explainability/provenance), and the underlying comparison object MUST remain inspectable.

#### Conversational chatbot

- **FR-008**: Each surfaced nudge MUST be selectable/clickable to open a chat conversation
  scoped to that nudge.
- **FR-009**: The chatbot MUST be grounded only in the selected nudge, its insight, and that
  day's comparison object and source signals; it MUST NOT invent metrics, recompute numbers,
  or reference data it was not provided.
- **FR-010**: The chatbot MUST be able to (a) explain why the nudge was raised in terms of
  the anomalous signals/trends, and (b) discuss the single suggested action and other simple
  non-clinical lifestyle actions.
- **FR-011**: The chatbot MUST maintain conversational context for the duration of an open
  chat session (multi-turn follow-ups). *(Superseded in Phase 3 — see FR-011a.)*
- **FR-011a** *(Phase 3)*: Chat sessions, their turns, and per-user agent memory MUST be
  persisted in a local store (SQLite) so the user can browse and resume prior conversations
  and so the assistant can carry memory (stated facts/preferences, conversation summaries,
  and deterministically-computed recurring data patterns) across chats. Each nudge opens its
  own resumable session; the user may also start free (non-nudge) chats grounded in the whole
  day's comparison object. Persistence is confined to the conversational layer and never
  alters deterministic analytics (constitution Principle VI, amended).
- **FR-012**: The chatbot MUST gracefully redirect questions outside the nudge's data scope
  ("I can only speak to this nudge's data") rather than fabricating an answer.

#### Safety (applies to nudges and chat)

- **FR-013**: All chatbot replies MUST obey the same associative-never-diagnostic rules as
  insights: no medical diagnosis, no clinical pathology, no disease prediction, no causation
  claims, and no emergency/clinical directives (except an explicitly configured
  extreme-anomaly rule).
- **FR-014**: The chatbot MUST decline requests for diagnosis, medication/dosage, or
  clinical treatment, and redirect to non-clinical lifestyle framing and, where appropriate,
  to consulting a qualified professional.
- **FR-015**: The chatbot MUST NOT be overridable by user prompts that attempt to remove its
  safety constraints or assign it a clinical/doctor role.
- **FR-016**: The informational-only (non-medical) disclaimer MUST be present on every nudge
  and on the chat surface.
- **FR-017**: Chatbot output that violates the safety rules MUST be caught and
  filtered/regenerated, never surfaced raw — consistent with the contract-first guarantee.

#### Presentation

- **FR-018**: The dashboard MUST present a nudge feed (one card per nudge: title, summary,
  single action) for the selected profile/day, each card opening that nudge's chat on click.
- **FR-019**: When there are no nudges for a day, the dashboard MUST show a clear "all
  steady" empty state rather than an empty or broken view.
- **FR-020**: The dashboard MUST keep the Phase 1 trend cards and the "generated from"
  explainability section, now linking each nudge to the signals that triggered it.

#### Cross-cutting

- **FR-021**: Anomaly detection MUST be deterministic and reproducible per seeded input and
  unit/golden-tested on fixed fixtures (exact anomalies raised for a given day).
- **FR-022**: The system MUST source the Anthropic API key from the environment and MUST NOT
  commit or log it; the deterministic suite (anomaly detection, nudge selection) MUST pass
  without a live key.

### Key Entities *(include if data involved)*

- **Anomaly**: a deterministically detected deviation for a given day/metric (e.g.
  `stress_elevated`, `steps_low`, `sleep_insufficient`, `hrv_depressed`), derived from
  comparison-object trend labels and threshold flags, with the source signal(s) that
  triggered it and a severity/priority for consolidation.
- **Nudge**: a user-facing, automatically raised item wrapping one hybrid Insight (title,
  associative narrative, single action, confidence, source signals) plus the triggering
  anomaly/anomalies; the unit a user clicks to start a chat.
- **Chat Session** *(Phase 3, persisted)*: a conversation with its grounding context and
  ordered turns, stored in the local SQLite chat store and resumable later. A session is
  either **nudge-anchored** (grounded in one nudge + the day's comparison object) or **free**
  (grounded in the whole day's comparison object). The assistant additionally draws on
  per-user **agent memory** — stated facts/preferences, conversation summaries, and
  deterministically-computed recurring data patterns — carried across sessions.
- **Insight** (reused from Phase 1): title, associative narrative summary, exactly one
  action, confidence level, source signals — schema-validated.
- **Comparison Object** (reused from Phase 1): the compact, LLM-facing grouped summary with
  current/baseline/deviation/flags and candidate associations; the grounding source for both
  nudge generation and chat.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For the built-in recovery-deficit day, the system raises an anomaly nudge
  automatically (no manual trigger) with a complete, schema-valid insight, end-to-end in a
  single run.
- **SC-002**: For an all-within-baseline day, the system raises zero nudges in 100% of runs
  (no fabricated problems).
- **SC-003**: 100% of raised nudges and 100% of chatbot replies pass automated safety checks
  (no diagnostic/causal phrasing, disclaimer present; nudges end in exactly one action).
- **SC-004**: When asked "why was this raised?", the chatbot's explanation references only
  the actual triggering signals for that day in 100% of evaluated cases (no fabricated
  metrics).
- **SC-005**: Across a probing safety test set (diagnosis, medication, ER, jailbreak
  prompts), the chatbot refuses/redirects appropriately in 100% of cases.
- **SC-006**: Anomaly detection is reproducible: the same seeded input yields the identical
  set of raised anomalies/nudges across 100% of runs.
- **SC-007**: A reviewer can trace every nudge back to the specific signals that triggered it
  via the explainability view in 100% of cases.
- **SC-008**: On a day with multiple anomalies, the dashboard never shows more than the
  configured maximum number of nudge cards (default 3).
- **SC-009**: A follow-up chat reply returns in a time acceptable for an interactive demo
  (target: under ~10 seconds excluding cold start).

## Assumptions

- This feature is additive to Phase 1: the deterministic analysis layers, the comparison
  object, and the hybrid insight contract are reused unchanged; only the experience layer
  (trigger model + chat) changes.
- Insight generation for nudges uses the same Claude provider and configurable model as
  Phase 1; no new LLM provider is introduced.
- The **analytics** pipeline remains stateless — nudges are derived per run, never stored.
  **Phase 3** adds a local SQLite store for the conversational layer only: chat sessions,
  turns, and per-user agent memory persist so history is browsable/resumable across runs.
- Anomaly thresholds reuse/extend the existing trend-label and threshold-flag logic; their
  exact values are configurable and documented in the plan, defaulting to the Phase 1
  ±15%-style banding.
- The default cap of 3 nudge cards per day is a reasonable demo default and is configurable.
- Reviewers/evaluators are non-clinical users assessing proactivity, clarity, and safety.
- Streamlit remains the primary demo surface; the optional REST API, if present, exposes the
  same nudge/chat engine and is not required for this feature.
- Out of scope for Phase 2 (deferred): push/notification delivery outside the app,
  cross-session memory or longitudinal nudge tracking, multi-user analytics, RAG-grounded
  chat, and any clinical/diagnostic capability.
