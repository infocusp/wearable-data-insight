# Feature Specification: Wearable Insights Translation Engine (Phase 1)

**Feature Branch**: `001-wearable-insights`

**Created**: 2026-06-18

**Status**: Draft

**Input**: Engineering plan in `Wearable_Insights_POC_Specification.md` — "Transform raw,
uninterpretable wearable metrics (sleep, recovery/HRV, stress, activity) into
empathetic, interpretable, and actionable daily insights using a deterministic
trend-analysis layer and a Claude-based explanation layer."

## Clarifications

### Session 2026-06-18

- Q: The source plan contains two conflicting specs (a minimal CLI pipeline and a fuller
  API + dashboard system). What should Phase 1 target? → A: Unified, incremental — one
  feature delivered as prioritized vertical slices: MVP single-profile pipeline first,
  then multi-profile trends, then associations, then dashboard, then CSV ingest, then an
  optional REST API.
- Q: Which LLM provider should generate insights? → A: OpenAI GPT (default model
  `gpt-4`), via the official SDK.
- Q: How should insights be shaped, and how should they treat cause vs. correlation? →
  A: Hybrid — schema-valid structured JSON whose summary is a readable physiological
  narrative phrased as *hypotheses/associations* ("may be linked to"), never hard
  causation; parseable for the dashboard and human-friendly.
- Q: What is the primary demo interface? → A: A single-page Streamlit dashboard.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Generate an actionable insight from a wearable snapshot (Priority: P1)

As a wearable user, I want my current day's metrics — interpreted against my own
recent baseline — turned into a short, empathetic explanation plus one concrete action,
so that I understand what my numbers mean and what to do today, instead of staring at
raw scores.

**Why this priority**: This is the core hypothesis of the entire PoC: that a
deterministic trend layer plus an LLM explanation layer can convert cold metrics into
interpretable, actionable guidance. If only this story ships, the project's central
question is already answered end-to-end.

**Independent Test**: Run the pipeline on a single built-in synthetic profile (the
"high-stress / sedentary recovery deficit" day) and confirm it produces a validated
insight object containing a narrative that references the relevant signals, exactly one
action step, a confidence level, and a non-medical, association-only tone — rendered to
the user in a minimal view.

**Acceptance Scenarios**:

1. **Given** a synthetic snapshot with a current day that is markedly below baseline on
   sleep, HRV, and steps and above baseline on stress, **When** the pipeline runs,
   **Then** it emits a schema-valid insight whose narrative connects those signals and
   ends with one concrete action for today.
2. **Given** the same snapshot, **When** the insight is generated, **Then** the output
   contains no medical diagnosis and no causal claims (only associative/hypothesis
   phrasing) and includes the informational-only disclaimer.
3. **Given** a snapshot whose current-day values are all within normal baseline,
   **When** the pipeline runs, **Then** the insight reflects a stable/steady state
   rather than inventing a problem.
4. **Given** the model returns output that does not satisfy the insight schema,
   **When** the pipeline processes it, **Then** the invalid output is rejected (and
   retried or surfaced as a handled error) rather than shown to the user raw.

---

### User Story 2 - Historical trends and personal baselines (Priority: P2)

As a wearable user, I want my current day compared against my own 7-day, 30-day, and
same-weekday history across realistic lifestyle patterns, so that the insight reflects
*my* normal rather than a generic population average.

**Why this priority**: Personalized baselines and trend direction are what make an
insight feel personal and accurate. They deepen P1's value but P1 is demonstrable
without them, so this comes second.

**Independent Test**: Generate the multi-profile synthetic dataset with a fixed seed and
verify that, for a chosen user/date, the engine computes correct 7-day / 30-day /
weekday baselines and assigns the expected up/down/stable trend labels per metric.

**Acceptance Scenarios**:

1. **Given** a seeded 90-day history for a "poor sleep week" profile, **When** baselines
   are computed for the latest day, **Then** the 7-day and 30-day means and the
   per-metric trend labels match the expected golden values.
2. **Given** the same seed, **When** the dataset is regenerated, **Then** it is
   identical (reproducible).
3. **Given** a day that falls within ±15% of baseline on a metric, **When** trends are
   labeled, **Then** that metric is labeled "stable".
4. **Given** fewer than 7 days of history exist for a user, **When** baselines are
   requested, **Then** the engine degrades gracefully (uses available history and flags
   reduced confidence) rather than failing.

---

### User Story 3 - Candidate associations enrich insights (Priority: P3)

As a wearable user, I want the system to surface *candidate relationships* between my
metrics (e.g. lower activity co-occurring with poorer sleep), clearly framed as
associations and not causes, so that the explanation connects the dots without
overclaiming.

**Why this priority**: Associations make the narrative richer and more useful, but the
insight is already valuable with raw deviations alone, so this layers on after baselines.

**Independent Test**: Feed the comparison engine a set of metric trends that match a
defined co-occurrence rule and confirm the corresponding non-causal association
candidate appears in the comparison object and is reflected (associatively) in the
insight.

**Acceptance Scenarios**:

1. **Given** sleep is down and stress is up for the day, **When** associations are
   generated, **Then** a "poor sleep and higher stress co-occur" candidate is produced,
   labeled explicitly as an association.
2. **Given** any generated association, **When** it is included in the comparison object,
   **Then** it never asserts causation.
3. **Given** no defined rule matches the day's trends, **When** associations are
   generated, **Then** the candidate list is empty and the insight still generates.

---

### User Story 4 - Insights dashboard (Priority: P4)

As a wearable user, I want a single screen that shows my key trend cards, my insight
cards (title, summary, suggested action), and a clear "generated from" explanation, so
that I can absorb my status and act at a glance and trust where the guidance came from.

**Why this priority**: The dashboard is the intended demo surface and makes the value
tangible, but every layer beneath it is independently testable first, so the UI comes
after the engine is sound.

**Independent Test**: Launch the dashboard for a selected profile/date and confirm it
renders trend cards for the key metrics, the insight card(s), the explainability
section linking insights to the source trends, and the disclaimer.

**Acceptance Scenarios**:

1. **Given** a generated insight, **When** the dashboard loads, **Then** it displays
   trend cards for sleep duration, sleep score, HRV, stress, and resting heart rate.
2. **Given** an insight, **When** the user views the explanation section, **Then** it
   lists the trends/signals the insight was generated from.
3. **Given** any view that shows insights, **When** it renders, **Then** the
   informational-only disclaimer is visible.

---

### User Story 5 - Bring-your-own data via CSV (Priority: P5)

As an evaluator, I want to upload a CSV of daily wearable summaries and get the same
trend analysis and insights, so that I can try the system on data beyond the built-in
synthetic profiles.

**Why this priority**: Useful for evaluation and broadens applicability, but synthetic
data fully exercises the pipeline, so external ingest is a later convenience.

**Independent Test**: Provide a CSV with the documented columns and confirm it is
normalized into canonical daily records (with missing values and out-of-range values
handled) and flows through the same analytics and insight path.

**Acceptance Scenarios**:

1. **Given** a CSV with the documented header and several days of rows, **When** it is
   ingested, **Then** each row becomes a canonical daily record with consistent units.
2. **Given** a CSV with a missing value in a cell, **When** it is ingested, **Then** the
   record is created with that field marked missing rather than the import failing.
3. **Given** a CSV with a value outside the valid range for a metric, **When** it is
   ingested, **Then** the value is flagged/quarantined per validation rules and the user
   is informed.

---

### User Story 6 - Programmatic access via REST API (Priority: P6, optional)

As an integrator, I want HTTP endpoints to submit records, trigger insight generation,
and inspect the intermediate comparison object, so that the engine can be driven
programmatically and debugged.

**Why this priority**: Optional for Phase 1 — the Streamlit dashboard satisfies the demo
goal. The API is valuable for integration and debugging but must reuse the same engine,
so it is the last slice.

**Independent Test**: Start the service and confirm `POST /ingest` accepts records,
`POST /generate-insights` returns the insight payload for a user/date, and
`GET /comparison-json` returns the intermediate comparison object for debugging.

**Acceptance Scenarios**:

1. **Given** the service is running, **When** a client posts valid records to `/ingest`,
   **Then** it responds with a success status.
2. **Given** ingested data, **When** a client posts a user/date to `/generate-insights`,
   **Then** it returns the same insight payload the dashboard would show.
3. **Given** ingested data, **When** a client calls `/comparison-json`, **Then** it
   returns the intermediate comparison object used for inference.

---

### Edge Cases

- **All metrics stable**: the insight must report steadiness and still give one helpful,
  low-stakes action — it must not fabricate a deficit.
- **Insufficient history** (< 7 or < 30 days): baselines use available data and the
  insight notes reduced confidence; the system never errors.
- **Missing / null metrics** for the current day: affected metrics are excluded from
  comparison and the narrative omits them rather than guessing.
- **Out-of-range / implausible values** (e.g. negative steps, sleep > 24h): flagged by
  validation and excluded or corrected per rules; never silently trusted.
- **Extreme anomaly**: only an explicitly configured extreme-anomaly rule may escalate
  tone; otherwise output stays within daily-optimization scope (no emergency advice).
- **LLM unavailable / errors / rate-limited**: handled gracefully with a clear message;
  the deterministic comparison object is still produced and inspectable.
- **LLM returns non-conforming output**: rejected and retried/handled; never shown raw.
- **Conflicting signals** (e.g. high stress but high HRV): the narrative acknowledges the
  mixed picture associatively rather than forcing a single story.

## Requirements *(mandatory)*

### Functional Requirements

#### Data & ingestion

- **FR-001**: The system MUST generate synthetic wearable data for distinct lifestyle
  profiles (at minimum: healthy/consistent, poor-sleep week, low-activity, recovery
  decline) over a configurable history window (default 90 days), from a fixed seed for
  reproducibility.
- **FR-002**: The system MUST include the targeted "high-stress / sedentary recovery
  deficit" snapshot (a current anomaly day plus its historical baseline context) as the
  P1 demonstration case.
- **FR-003**: The system MUST normalize all inputs into a single canonical daily record
  schema with consistent units.
- **FR-004**: The system MUST handle missing values (mark, do not fail) and validate
  numeric ranges (flag/quarantine out-of-range values).
- **FR-005**: The system MUST support importing daily summaries from a CSV with a
  documented column set (date, sleep duration, sleep score, deep sleep, REM sleep,
  resting HR, HRV, stress score, steps, active minutes).

#### Analysis (deterministic)

- **FR-006**: The system MUST compute derived features (deltas for sleep duration/score,
  deep/REM sleep, resting HR, HRV, stress, steps, active minutes; plus sleep consistency
  and bedtime shift where data allows) in code, not via the LLM.
- **FR-007**: The system MUST compute per-user baselines: current day, 7-day mean,
  30-day mean, and same-weekday baseline.
- **FR-008**: The system MUST assign each tracked metric a trend label of `up`, `down`,
  or `stable`, treating deviations within ±15% of baseline as `stable`.
- **FR-009**: The system MUST produce a compact comparison object grouping sleep, heart
  health/recovery, and activity, each with current values, baselines, deviations, and
  threshold flags — and MUST NOT pass raw daily tables to the LLM.
- **FR-010**: The system MUST generate candidate associations from defined co-occurrence
  rules (e.g. sleep↓ & stress↑; steps↓ & sleep↓; HRV↓ & stress↑), each labeled as an
  association and never as causation.
- **FR-011**: Given identical input data and configuration, the comparison object MUST be
  reproducible (deterministic) regardless of the LLM.

#### Insight generation (LLM)

- **FR-012**: The system MUST generate insights by sending the comparison object to
  Anthropic Claude (default model configurable, `claude-sonnet-4-6`) and MUST NOT ask the
  model to perform calculations.
- **FR-013**: The system MUST constrain the model to return a schema-valid insight
  payload containing, per insight: a title, a narrative summary, exactly one action
  step, a confidence level, and the list of source signals it was derived from.
- **FR-014**: The narrative MUST use associative / hypothesis language and MUST NOT
  contain medical diagnoses, clinical pathology, disease prediction, or emergency
  directives (except under an explicitly configured extreme-anomaly rule).
- **FR-015**: Every insight MUST conclude with exactly one concrete, physically
  actionable directive for the current day.
- **FR-016**: The system MUST reject LLM output that fails schema validation and either
  retry or surface a handled error — never display invalid output.
- **FR-017**: The system MUST NOT merely echo raw numbers ("your sleep score is 61");
  the narrative MUST interpret the data physiologically and at a human level.

#### Presentation & access

- **FR-018**: The system MUST present, on a single-page dashboard, trend cards for key
  metrics (sleep duration, sleep score, HRV, stress, resting HR), insight card(s)
  (title, summary, suggested action), and a "generated from" explainability section.
- **FR-019**: Every surface that shows insights MUST display an informational-only
  (non-medical) disclaimer.
- **FR-020**: The system SHOULD (optional slice) expose REST endpoints to ingest records
  (`/ingest`), generate insights (`/generate-insights`), and retrieve the intermediate
  comparison object (`/comparison-json`) for debugging — reusing the same engine.

#### Cross-cutting

- **FR-021**: The system MUST source the Anthropic API key from the environment and MUST
  NOT commit or log it.
- **FR-022**: The intermediate comparison object MUST be retrievable/inspectable for
  debugging and evaluation.
- **FR-023**: The deterministic analytics layers MUST be unit/golden-tested on fixed
  fixtures asserting exact computed values, flags, and trend labels.

### Key Entities *(include if feature involves data)*

- **User Profile**: a synthetic (or imported) individual with minimal metadata
  (id, optional age/gender) and a time-ordered history of daily records.
- **Canonical Daily Record**: one day for one user — sleep (duration, score, deep, REM),
  recovery (resting HR, HRV, stress), activity (steps, active minutes), with units and
  missing/validity flags.
- **Baseline Set**: per-user, per-metric current value plus 7-day, 30-day, and
  same-weekday reference values for a given analysis date.
- **Comparison Object**: the compact, LLM-facing summary — grouped sections (sleep, heart
  health, activity) with current/baseline/deviation/flags, plus a list of candidate
  associations; the contract between analysis and inference.
- **Candidate Association**: a non-causal relationship between metric trends produced by
  a defined co-occurrence rule, with a stable identifier/relation label.
- **Insight**: the user-facing result — title, narrative summary, single action,
  confidence level, and source signals — schema-validated.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For the P1 recovery-deficit case, the system produces a complete, valid
  insight (narrative + exactly one action + confidence + source signals) end-to-end in a
  single run.
- **SC-002**: In a blind review, evaluators prefer the generated insight over the raw
  metric ("your sleep score is 65") for at least 80% of presented cases.
- **SC-003**: At least 90% of reviewers rate the suggested action as a useful, doable
  step for the day.
- **SC-004**: 100% of generated insights pass automated safety checks (no diagnostic /
  causal phrasing, exactly one action step, disclaimer present).
- **SC-005**: 100% of insights surfaced to the user are schema-valid (no raw or
  malformed model output ever reaches the UI).
- **SC-006**: Deterministic analytics are reproducible: regenerating the comparison
  object from the same seeded input yields identical results across 100% of runs.
- **SC-007**: A reviewer can trace every displayed insight back to the specific
  trends/signals that produced it via the explainability view.
- **SC-008**: From synthetic data to displayed insight, a single profile/day completes in
  a time acceptable for an interactive demo (target: under ~10 seconds excluding cold
  start), so the demo feels responsive.

## Assumptions

- The objective is to validate feasibility of interpretable, actionable guidance — not
  medical accuracy; insights are lifestyle guidance only.
- Phase 1 runs on synthetic data (and optional user-provided CSV); no live device/API
  integrations and no real PHI.
- Synthetic profiles and the targeted anomaly are representative enough to demonstrate
  the value proposition to reviewers.
- A valid `ANTHROPIC_API_KEY` is available in the environment for live insight
  generation; deterministic tests run without it.
- A single-user-at-a-time, stateless, single-pass flow is sufficient for Phase 1; no
  persistence layer or multi-user analytics is required.
- Reviewers/evaluators are non-clinical users assessing interpretability and usefulness.
- Out of scope for Phase 1 (deferred to later phases): raw PPG/ECG processing, clinical
  recommendations, disease prediction, RAG knowledge base, personalized physiology
  models, multi-user population analytics, real-time streaming, and live provider OAuth
  integrations.
