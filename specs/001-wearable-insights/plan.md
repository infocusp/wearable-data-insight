# Implementation Plan: Wearable Insights Translation Engine (Phase 1)

**Branch**: `001-wearable-insights` | **Date**: 2026-06-18 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-wearable-insights/spec.md`

## Summary

Build a stateless, single-pass pipeline that turns wearable daily summaries into
empathetic, interpretable, actionable insights. Deterministic Python layers ingest /
normalize data, compute features, personal baselines (7d/30d/weekday), trend labels, and
non-causal candidate associations, then assemble a compact **comparison object**. That
object — never raw tables — is sent to **Anthropic Claude** (`claude-sonnet-4-6`,
configurable) which returns a **schema-valid hybrid insight**: structured JSON whose
narrative uses cautious, associative language and ends in exactly one action. A Streamlit
dashboard renders trend cards, insight cards, and explainability; a thin FastAPI service
is an optional last slice. Delivered as prioritized vertical slices (P1 MVP → P6).

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: `anthropic` (official SDK, insight generation via
`messages.parse` with a Pydantic schema + adaptive thinking); `pydantic` v2 (canonical
record, comparison object, and insight models + validation); `streamlit` (dashboard,
P4); `fastapi` + `uvicorn` (optional REST service, P6); `pytest` (tests); `ruff`
(lint + format); `jsonschema` (contract tests against `contracts/`). Analytics use the
Python standard library (`statistics`, `datetime`); `numpy`/`pandas` are optional and
only if they simplify the trend math.

**Storage**: N/A for Phase 1 — stateless, single-pass. Inputs are the seeded synthetic
generator or an uploaded CSV; intermediate artifacts (`comparison object`) are passed
in-memory and optionally written as JSON for inspection. No database.

**Testing**: `pytest`. Deterministic analytics covered by unit + golden-fixture tests;
the LLM boundary tested with a stubbed client (no live key needed); JSON-Schema contract
tests; a small optional live smoke test gated on `ANTHROPIC_API_KEY`.

**Target Platform**: Local developer machine (Linux/macOS), Python CLI + Streamlit app;
optional local FastAPI service.

**Project Type**: Single project — a `wearable_insights` library with thin CLI, Streamlit,
and (optional) API entry points layered on top.

**Performance Goals**: Interactive demo responsiveness — a single profile/day from data
to displayed insight in under ~10 s excluding model cold start (SC-008). Deterministic
layers are sub-second on a 90-day history.

**Constraints**: Deterministic analytics (byte-identical comparison object per seed/config,
independent of the LLM); LLM output must be schema-valid before it reaches the user; no
real PHI (synthetic/CSV only); `ANTHROPIC_API_KEY` from env, never committed or logged;
associative-only, non-diagnostic insight tone.

**Scale/Scope**: Single user at a time, ~4 synthetic profiles × ~90 days each, one
analysis date per run. ~12–15 source modules; not a high-throughput service.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| # | Principle | How this plan satisfies it | Status |
|---|-----------|----------------------------|--------|
| I | Deterministic Analysis Before Inference | All math lives in `normalize`/`features`/`trends`/`comparison`/`associations`; LLM receives only the comparison object and is never asked to compute. Reproducibility asserted by golden tests (FR-006, FR-009, FR-011). | PASS |
| II | Associative, Never Diagnostic (NON-NEGOTIABLE) | System prompt enforces associative phrasing + one action + disclaimer; a `safety` module + tests reject diagnostic/causal output (FR-014, FR-015, FR-019, SC-004). | PASS |
| III | Contract-First Structured Data | `contracts/` holds JSON Schemas for canonical record, comparison object, and insight; runtime uses Pydantic mirrors; `messages.parse` constrains LLM output; invalid output rejected (FR-013, FR-016, SC-005). | PASS |
| IV | Independently-Testable Vertical Slices | Stories P1–P6 each ship a standalone, testable increment; P1 is a viable MVP; later slices are additive (tasks.md is organized by story). | PASS |
| V | Explainability & Provenance | Each insight carries `source_signals`; dashboard shows a "generated from" section; comparison object is retrievable (FR-018, FR-022, SC-007). | PASS |
| VI | Reproducibility & Privacy by Default | Seeded synthetic generator; synthetic/CSV only (no PHI); key sourced from env (FR-001, FR-021, SC-006). | PASS |

**Technology constraints**: Python 3.11+, Claude via `anthropic` SDK (default
`claude-sonnet-4-6`, configurable), stateless single-pass, Streamlit primary + optional
FastAPI reusing the same engine — all consistent with the constitution's Technology &
Architecture Constraints. No deviations.

**Result**: Constitution Check PASSES. No entries required in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/001-wearable-insights/
├── spec.md              # Feature spec (input)
├── plan.md              # This file
├── research.md          # Phase 0 — decisions & rationale
├── data-model.md        # Phase 1 — entities & schemas
├── quickstart.md        # Phase 1 — setup & run
├── contracts/           # Phase 1 — JSON Schemas + OpenAPI
│   ├── canonical_record.schema.json
│   ├── comparison_object.schema.json
│   ├── insight.schema.json
│   └── rest-api.openapi.yaml
└── tasks.md             # Phase 2 — produced by /speckit.tasks
```

### Source Code (repository root)

```text
src/wearable_insights/
├── __init__.py
├── config.py                 # settings: model id, thresholds, seed, paths; reads ANTHROPIC_API_KEY from env
├── models.py                 # Pydantic v2: CanonicalDailyRecord, BaselineSet, ComparisonObject, CandidateAssociation, Insight, InsightSet
├── normalize.py              # raw/dict → CanonicalDailyRecord; missing-value + range validation (FR-003, FR-004)
├── features.py               # derived deltas, sleep consistency, bedtime shift (FR-006)
├── trends.py                 # 7d/30d/weekday baselines + up/down/stable labels (FR-007, FR-008)
├── comparison.py             # build compact ComparisonObject from baselines/trends (FR-009)
├── associations.py           # co-occurrence rules → CandidateAssociation list (FR-010)
├── safety.py                 # associative-tone / one-action / disclaimer checks (FR-014, FR-015, FR-019)
├── pipeline.py               # orchestrate snapshot → comparison → insight (FR-022)
├── data/
│   ├── __init__.py
│   ├── synthetic.py          # seeded generator: 4 profiles × 90 days + recovery-deficit snapshot (FR-001, FR-002)
│   └── csv_ingest.py         # CSV → CanonicalDailyRecord[] (FR-005)
├── llm/
│   ├── __init__.py
│   ├── client.py             # Anthropic wrapper: messages.parse(Insight schema), adaptive thinking, retries (FR-012, FR-016)
│   ├── prompt.py             # system prompt (associative rules, examples) + user-payload assembly (FR-013, FR-017)
│   └── insight.py            # generate_insights(ComparisonObject) → InsightSet
├── cli.py                    # P1 minimal rendering of the insight
├── app.py                    # P4 Streamlit dashboard: trend cards, insight cards, explainability, disclaimer (FR-018, FR-019)
└── api.py                    # P6 optional FastAPI: /ingest, /generate-insights, /comparison-json (FR-020)

tests/
├── conftest.py               # fixtures + stubbed LLM client
├── fixtures/                 # golden comparison objects + sample CSV + stubbed insight payloads
├── unit/
│   ├── test_normalize.py
│   ├── test_features.py
│   ├── test_trends.py
│   ├── test_comparison.py
│   ├── test_associations.py
│   ├── test_synthetic_reproducible.py
│   ├── test_safety.py
│   └── test_prompt_assembly.py
├── contract/
│   ├── test_canonical_record_schema.py
│   ├── test_comparison_schema.py
│   └── test_insight_schema.py
└── integration/
    ├── test_pipeline_p1.py   # end-to-end with stubbed LLM
    ├── test_csv_ingest.py
    └── test_api.py           # optional, with stubbed LLM

pyproject.toml                # deps, ruff + pytest config, console-script entry points
.env.example                  # ANTHROPIC_API_KEY=, WEARABLE_MODEL=claude-sonnet-4-6
README.md
```

**Structure Decision**: Single-project layout. A pure `wearable_insights` library holds
all deterministic analytics and the LLM boundary; CLI (`cli.py`), Streamlit (`app.py`),
and the optional API (`api.py`) are thin presentation layers that call `pipeline.py`, so
each interface slice reuses one engine (Constitution: optional API "MUST reuse the same
analytics and LLM modules, not duplicate them"). Design-time JSON Schemas live in
`contracts/`; runtime validation uses the Pydantic mirrors in `models.py`, with contract
tests asserting the two stay in sync.

## Complexity Tracking

> No Constitution Check violations — this section is intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
