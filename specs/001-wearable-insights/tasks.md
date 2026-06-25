---
description: "Dependency-ordered task list for the Wearable Insights Translation Engine (Phase 1)"
---

# Tasks: Wearable Insights Translation Engine (Phase 1)

**Input**: Design documents from `/specs/001-wearable-insights/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Test tasks are **included and required** here — the project constitution
(Quality Gates) and FR-023 mandate golden/contract/safety tests for the deterministic
layers and the LLM boundary. They are not optional for this feature.

**Organization**: Grouped by user story (US1–US6) so each story is implemented, tested,
and demoed independently. US1 is the MVP.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on another unfinished task)
- **[Story]**: the user story a task belongs to (US1–US6)
- File paths are relative to the repository root and follow `plan.md` § Project Structure.

## Phase 1: Setup (Shared Infrastructure)

- [ ] T001 Create the package skeleton: `src/wearable_insights/__init__.py`,
  `src/wearable_insights/data/__init__.py`, `src/wearable_insights/llm/__init__.py`, and
  `tests/{unit,contract,integration,fixtures}/` directories.
- [ ] T002 Author `pyproject.toml` — dependencies (`anthropic`, `pydantic>=2`,
  `streamlit`, `fastapi`, `uvicorn`, `jsonschema`, `pytest`, `ruff`), a `[dev]` extra, and
  console entry point `wearable-insights = wearable_insights.cli:main`.
- [ ] T003 [P] Configure `ruff` (lint + format) and `pytest` (markers incl. `live`) in
  `pyproject.toml`; add `tests/` to test paths.
- [ ] T004 [P] Add `.env.example` (`ANTHROPIC_API_KEY=`, `WEARABLE_MODEL=claude-sonnet-4-6`)
  and `src/wearable_insights/config.py` (load env, expose model id, ±15% threshold,
  default seed, default history window, disclaimer text).

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T005 Implement all Pydantic v2 models in `src/wearable_insights/models.py`
  (`CanonicalDailyRecord`, `MetricBaseline`, `BaselineSet`, `MetricComparison`,
  `ComparisonSection`, `ComparisonObject`, `CandidateAssociation`, `Insight`,
  `InsightSet`) mirroring `data-model.md` and `contracts/`.
- [ ] T006 [P] Contract-test scaffolding in `tests/contract/` — load
  `contracts/*.schema.json` with `jsonschema`, plus a model↔schema sync check that a
  representative model instance validates against its schema
  (`test_canonical_record_schema.py`, `test_comparison_schema.py`,
  `test_insight_schema.py`).
- [ ] T007 Implement `src/wearable_insights/normalize.py` — map raw dict/row →
  `CanonicalDailyRecord`, record `missing_fields`, quarantine out-of-range values into
  `invalid_fields` (never raise) (FR-003, FR-004).
- [ ] T008 [P] `tests/unit/test_normalize.py` — missing cell, out-of-range value, stages
  exceeding total sleep, happy path.
- [ ] T009 [P] `tests/conftest.py` — a stubbed Anthropic client returning canned,
  schema-valid `InsightSet` payloads from `tests/fixtures/`, plus fixture loaders for
  golden comparison objects and a sample CSV.

**Checkpoint**: Models, normalization, and test harness ready — stories can begin.

---

## Phase 3: User Story 1 - Generate an actionable insight (Priority: P1) 🎯 MVP

**Goal**: End-to-end single-snapshot → deterministic comparison → Claude → schema-valid,
safety-checked insight, rendered via CLI.

**Independent Test**: `python -m wearable_insights.cli --profile recovery_deficit`
produces a complete, valid, associative insight with exactly one action and the
disclaimer.

- [ ] T010 [US1] `src/wearable_insights/data/synthetic.py` — the built-in
  "recovery deficit" snapshot (current anomaly day + 30-day baseline averages) (FR-002).
- [ ] T011 [US1] `src/wearable_insights/features.py` — per-metric deltas vs the snapshot's
  baseline averages (FR-006).
- [ ] T012 [US1] `src/wearable_insights/comparison.py` — build a `ComparisonObject` from
  the snapshot: current vs baseline, `percentage_change`, `trend` (±15% dead-band),
  `evaluation_tag`, and `flags`; `data_quality` populated (FR-009).
- [ ] T013 [P] [US1] `src/wearable_insights/llm/prompt.py` — system prompt encoding the
  associative/non-diagnostic rules + one-action rule + good/bad example pair, and a
  user-payload assembler that embeds the comparison object (FR-013, FR-017); mark the
  system prompt cacheable.
- [ ] T014 [US1] `src/wearable_insights/llm/client.py` — Anthropic wrapper using
  `messages.parse(output_format=InsightSet)`, adaptive thinking, `effort="medium"`, env
  key, and retry-on-invalid (FR-012, FR-016).
- [ ] T015 [US1] `src/wearable_insights/llm/insight.py` —
  `generate_insights(ComparisonObject) -> InsightSet` orchestration (prompt → client →
  parsed payload).
- [ ] T016 [US1] `src/wearable_insights/safety.py` — assert exactly one action, disclaimer
  present, no banned diagnostic/causal phrasing, `source_signals ⊆ comparison signals`;
  raise a typed error that triggers retry/handled failure (FR-014, FR-015, FR-019).
- [ ] T017 [US1] `src/wearable_insights/pipeline.py` — orchestrate snapshot → comparison →
  insight → safety; option to dump the comparison object to JSON (FR-022).
- [ ] T018 [US1] `src/wearable_insights/cli.py` — `--profile`, `--dump-comparison`; render
  title/summary/action/confidence + disclaimer; `main()` entry point.
- [ ] T019 [P] [US1] `tests/contract/test_insight_schema.py` — a generated/stubbed
  `InsightSet` validates against `contracts/insight.schema.json` (SC-005).
- [ ] T020 [P] [US1] `tests/unit/test_safety.py` — passes clean output; rejects
  diagnostic/causal phrasing, multi-action, and missing disclaimer (SC-004).
- [ ] T021 [P] [US1] `tests/unit/test_prompt_assembly.py` — payload contains the
  comparison object and no raw daily tables; system prompt includes the rules.
- [ ] T022 [US1] `tests/integration/test_pipeline_p1.py` — end-to-end with the stubbed
  client: recovery-deficit snapshot → valid insight (SC-001).

**Checkpoint**: MVP is fully functional and demoable on its own.

---

## Phase 4: User Story 2 - Historical trends and personal baselines (Priority: P2)

**Goal**: Real 7d/30d/weekday baselines and trend labels over a seeded multi-profile
dataset, replacing the snapshot-only comparison path.

**Independent Test**: For a seeded profile/date, computed baselines and trend labels match
the golden values; regeneration is identical.

- [ ] T023 [US2] Extend `src/wearable_insights/data/synthetic.py` — seeded generator for 4
  profiles (healthy-consistent, poor-sleep week, low-activity, recovery-decline) ×
  configurable window (default 90 days) (FR-001).
- [ ] T024 [P] [US2] `tests/unit/test_synthetic_reproducible.py` — same seed ⇒ identical
  dataset (FR-001, SC-006).
- [ ] T025 [US2] `src/wearable_insights/trends.py` — `BaselineSet` with 7d/30d/weekday
  means, `up/down/stable` labels (±15% dead-band), and `low_confidence` for short history
  (FR-007, FR-008).
- [ ] T026 [P] [US2] `tests/unit/test_trends.py` — golden baselines/labels; ±15% boundary;
  `< 7` days degrades gracefully; null/zero-baseline → `stable` + low confidence.
- [ ] T027 [US2] Extend `src/wearable_insights/comparison.py` — build the
  `ComparisonObject` from a `BaselineSet` (full-history path) including
  `Critically *` tags for |Δ| ≥ 50% (FR-009).
- [ ] T028 [P] [US2] `tests/unit/test_comparison.py` — golden comparison object from a
  fixed baseline set (deterministic, SC-006).
- [ ] T029 [US2] Extend `src/wearable_insights/pipeline.py` — `profile + analysis_date →
  trends → comparison → insight` path.
- [ ] T030 [US2] Extend `src/wearable_insights/cli.py` — `--analysis-date` and
  profile/day selection over the multi-profile dataset.

**Checkpoint**: US1 and US2 both work independently.

---

## Phase 5: User Story 3 - Candidate associations enrich insights (Priority: P3)

**Goal**: Non-causal co-occurrence candidates in the comparison object and reflected
associatively in insights.

**Independent Test**: A trend set matching a rule yields the expected association; no rule
match yields an empty list and the insight still generates.

- [ ] T031 [US3] `src/wearable_insights/associations.py` — rules R1 (sleep↓ & stress↑),
  R2 (steps↓ & sleep↓), R3 (HRV↓ & stress↑) → `CandidateAssociation[]`, each
  `kind:"association"` (FR-010).
- [ ] T032 [P] [US3] `tests/unit/test_associations.py` — each rule fires correctly; empty
  case; invariant that output never asserts causation.
- [ ] T033 [US3] Extend `src/wearable_insights/comparison.py` — populate
  `candidate_associations` from `associations.py`.
- [ ] T034 [US3] Extend `src/wearable_insights/llm/prompt.py` — surface associations in the
  payload, instructing associative-only phrasing.

**Checkpoint**: US1–US3 all work independently.

---

## Phase 6: User Story 4 - Insights dashboard (Priority: P4)

**Goal**: Single-page Streamlit dashboard: trend cards, insight cards, explainability,
disclaimer.

**Independent Test**: Launch the dashboard for a profile/date; all four regions render.

- [ ] T035 [US4] `src/wearable_insights/app.py` — profile/date selector wired to
  `pipeline.py`; trend cards for sleep duration, sleep score, HRV, stress, resting HR
  (FR-018).
- [ ] T036 [US4] `src/wearable_insights/app.py` — insight cards (title, summary, action,
  confidence) (FR-018).
- [ ] T037 [US4] `src/wearable_insights/app.py` — "generated from" explainability section
  linking insights to source signals/trends (SC-007) + visible disclaimer (FR-019).
- [ ] T038 [US4] `src/wearable_insights/app.py` — graceful handling/UI when the LLM is
  unavailable or output is rejected (still show the comparison object).

**Checkpoint**: Visual demo surface complete.

---

## Phase 7: User Story 5 - Bring-your-own data via CSV (Priority: P5)

**Goal**: Ingest a documented CSV into canonical records through the same pipeline.

**Independent Test**: A documented CSV (incl. a missing cell and an out-of-range value)
ingests into canonical records and flows to insights.

- [ ] T039 [US5] `src/wearable_insights/data/csv_ingest.py` — parse the documented header,
  map each row via `normalize.py` → `CanonicalDailyRecord[]` (FR-005).
- [ ] T040 [P] [US5] `tests/integration/test_csv_ingest.py` — header parse, missing cell
  marked, out-of-range quarantined + reported.
- [ ] T041 [US5] Wire CSV input: `--csv` in `cli.py` and a file-uploader path in
  `app.py`.

**Checkpoint**: External data supported.

---

## Phase 8: User Story 6 - Programmatic access via REST API (Priority: P6, optional)

**Goal**: Thin FastAPI surface reusing the engine.

**Independent Test**: `/ingest`, `/generate-insights`, `/comparison-json` behave per the
OpenAPI contract.

- [ ] T042 [US6] `src/wearable_insights/api.py` — FastAPI app with `POST /ingest`,
  `POST /generate-insights`, `GET /comparison-json`, calling `pipeline.py` (no duplicated
  logic) (FR-020); error mapping per `contracts/rest-api.openapi.yaml`.
- [ ] T043 [P] [US6] `tests/integration/test_api.py` — endpoints with the stubbed client;
  responses validate against the OpenAPI/JSON schemas.

**Checkpoint**: Programmatic access available.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [ ] T044 [P] `README.md` — overview, architecture diagram, run instructions (links to
  `quickstart.md`).
- [ ] T045 [P] `tests/test_live_smoke.py` (marker `live`) — real-model generation produces
  a valid, safety-passing insight when `ANTHROPIC_API_KEY` is set.
- [ ] T046 Run `quickstart.md` end-to-end and confirm the Definition of Done (SC-001,
  SC-005).
- [ ] T047 [P] Final `ruff check`/`ruff format`; confirm the full deterministic suite
  passes with **no** API key set.
- [ ] T048 [P] Cross-check FR-019: a single disclaimer constant (from `config.py`) is
  surfaced on CLI, dashboard, and API responses.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (P1)** → no deps.
- **Foundational (P2)** → after Setup; **blocks all stories**.
- **US1 (P3)** → after Foundational. The MVP.
- **US2 (P4)** → after Foundational; replaces US1's snapshot-only comparison path with the
  full trend engine (touches `comparison.py`/`pipeline.py`/`cli.py` — sequence after US1).
- **US3 (P5)** → after US2 (associations consume trend labels).
- **US4 (P6)** → after US1 (needs a working pipeline); richer with US2/US3.
- **US5 (P7)** → after Foundational (uses `normalize.py`); demoable once a pipeline exists
  (US1).
- **US6 (P8)** → after US1 (wraps the pipeline); optional.
- **Polish (P9)** → after the desired stories.

### Within each story

- Tests for deterministic modules are written against fixed fixtures alongside the module.
- Models → analytics → comparison → LLM → orchestration → presentation.
- A later story must not break an earlier one (additive integration; constitution IV).

### Parallel opportunities

- Setup: T003, T004 in parallel.
- Foundational: T006, T008, T009 in parallel (after T005/T007 land their targets).
- US1: T013, T019, T020, T021 in parallel; T010–T012 (analytics) can proceed alongside.
- US2: T024, T026, T028 in parallel.
- Different stories can proceed in parallel once Foundational is done, except where they
  edit the same file (`comparison.py`, `pipeline.py`, `cli.py`, `app.py`) — serialize
  those.

---

## Implementation Strategy

### MVP first (recommended)

1. Setup (Phase 1) → Foundational (Phase 2) → **US1 (Phase 3)**.
2. **Stop and validate**: run the MVP independent test; confirm SC-001/004/005.
3. Demo, then proceed to US2 → US3 → US4, validating each at its checkpoint.

### Incremental delivery

Each story is a deployable increment that adds value without breaking the previous one:
US1 (insight) → US2 (personal baselines) → US3 (associations) → US4 (dashboard) →
US5 (CSV) → US6 (API).

---

## Notes

- `[P]` = different files, no blocking dependency.
- `[Story]` ties a task to a user story for traceability.
- Keep secrets in the environment; the deterministic suite must pass without a key.
- Commit after each task or logical group; stop at any checkpoint to validate a story
  independently.
