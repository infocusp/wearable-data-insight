# Implementation Plan: Live-Stream-Driven Automatic Nudges

**Branch**: `003-live-auto-nudges` | **Date**: 2026-06-24 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-live-auto-nudges/spec.md`

## Summary

Make nudges automatic and driven by the **live intraday vitals stream** instead of a manual
button. This deliberately reverses the Phase-2 "live vitals are presentation-only" decision,
but stays inside the constitution: live anomaly detection is pure, seeded, reproducible Python,
and the LLM still receives a pre-computed, comparison-shaped object — never raw samples.

Three additive layers, reusing the existing nudge/insight/safety stack unchanged where possible:

1. **Deterministic live-anomaly detection** — a new `live_anomaly.py` evaluates the rolling
   live buffer (`data/live.py`) over a trailing window, comparing each signal's windowed mean
   to the day's anchor (the per-signal baseline `live.live_baselines` already derives). Sustained
   deviations beyond the existing severity thresholds become `Anomaly` records. New anomaly
   codes/themes cover the already-streamed signals **SpO₂, skin temperature, respiration rate**
   (plus HR-elevated), alongside the existing HRV-depressed mapping. Windowing suppresses
   single-sample noise (FR-005). The activity context (resting/active/stressed) shifts the live
   anchors, so switching to *stressed* drives HRV down / respiration & HR up and fires the
   matching anomalies (FR-004).

2. **Synthesized comparison + reused nudge generation** — `live_anomaly.py` builds a lightweight
   `ComparisonObject` (live windowed value as `current_value`, the day's anchor as the monthly
   `baseline_value`, with `percentage_change`/`evaluation_tag` filled deterministically) placing
   the live vitals under `heart_health`. The existing `nudges.generate_nudge_set(...)` then runs
   unchanged: it consolidates by theme, caps at `MAX_NUDGES_PER_DAY`, generates each `Insight`
   via `llm/insight.py`, and gates it through `safety.py`. The only edit to `nudges.py` is
   extending `_focused_comparison`'s theme→section map to recognise the new vitals themes
   (still reading from `heart_health`) — one generation codepath, one safety gate (FR-007, FR-008).

3. **Automatic, bounded, de-duplicated feed in the live panel** — `ui/live_panel.py`'s
   `@st.fragment(run_every=…)` loop, after appending each new sample, calls the live detector,
   applies episode de-duplication + a cooldown re-raise rule (FR-010, FR-016), generates nudges
   for genuinely new anomalies, and surfaces them. A small `live_nudge_state` in `session_state`
   tracks active episodes and last-raised timestamps; the bounded `nudge_set` is shared with the
   existing chat column so auto-nudges are chat-able exactly like manual ones. The manual
   "Simulate Nudge" button is demoted to a hidden/debug fallback (FR-017).

No new dependency, no new LLM provider, no persistence. The deterministic daily-summary pipeline
(`build_comparison` / `run_nudge_pipeline`) and the daily-summary chat are untouched (FR-012).

## Technical Context

**Language/Version**: Python 3.11+ (unchanged).

**Primary Dependencies**: Reuses the existing stack — `anthropic` SDK (per-nudge insight via
`llm/insight.py` → `messages.parse(InsightSet)`), `pydantic` v2 (extend `AnomalyCode`/
`AnomalyTheme` enums; new optional config knobs), `streamlit` (`st.fragment(run_every=…)`,
`st.session_state`), `pytest`, `ruff`, `jsonschema`. **No new third-party dependency.**

**Storage**: N/A. Live detection is stateless per evaluation; episode/cooldown bookkeeping and
the bounded `nudge_set` live only in Streamlit `session_state` and reset on profile/source change.

**Testing**: `pytest`, no API key required for the deterministic suite. New golden unit tests for
`live_anomaly.py` (sustained deviation → exact anomalies; transient spike → none; reproducible
per seed/context/timing) and the synthesized-comparison builder (correct `current_value`,
`baseline_value`, `evaluation_tag`). Nudge generation from a synthesized comparison is tested
with a **stubbed** generate-fn (no live key). Optional `-m live` smoke for one real auto-nudge.

**Target Platform**: Local dev machine (Linux/macOS), Streamlit dashboard as the demo surface.

**Performance Goals**: A stressed-context switch surfaces a relevant nudge within ≤ 6 live syncs
(SC-001). Deterministic live detection over the rolling buffer is sub-millisecond; the only slow
step is the per-nudge model call, which must not freeze the auto-refreshing signal cards (see
Constraints + research R3).

**Constraints**: Live detection is deterministic/seed-reproducible (Principle I, SC-003); the LLM
never decides anomalies and never sees raw samples — only the synthesized `ComparisonObject`
(Principle I). All nudges stay associative, single-action, disclaimer-bearing, safety-gated
(Principle II, SC-002). The feed is bounded by `MAX_NUDGES_PER_DAY` and de-duplicated per episode
with a cooldown re-raise (FR-009, FR-010, FR-016). Graceful degradation with no API key — signals
keep refreshing, no blocking error (FR-013, SC-007). `ANTHROPIC_API_KEY` from env only.

**Scale/Scope**: One user / one open dashboard session at a time; ≤ `MAX_NUDGES_PER_DAY` nudges
surfaced; ~1 new source module (`live_anomaly.py`), small edits to `models.py`, `config.py`,
`nudges.py`, `ui/live_panel.py`, `app.py`; live signal simulator (`data/live.py`) unchanged.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| # | Principle | How this plan satisfies it | Status |
|---|-----------|----------------------------|--------|
| I | Deterministic Analysis Before Inference | `live_anomaly.py` detects anomalies and synthesizes the comparison object in pure, seeded Python from the live buffer; the LLM only writes the nudge narrative from that object and never sees raw samples or computes deviations. Golden tests assert exact anomalies and reproducibility per seed/context/timing (FR-001, FR-005, FR-006, SC-003). | PASS |
| II | Associative, Never Diagnostic (NON-NEGOTIABLE) | Nudges reuse the unchanged `llm/insight.py` + `safety.py` path; every reply stays associative, single-action, disclaimer-bearing, and safety-gated; failing nudges are skipped, never surfaced (FR-008, SC-002). SpO₂/skin-temp/respiration anomalies describe *associations*, not diagnoses. | PASS |
| III | Contract-First Structured Data | New `Anomaly` codes/themes and the synthesized `ComparisonObject` validate against the existing (extended) schemas; a `contracts/live_anomaly.schema.json` documents the live-anomaly shape; nudge insights stay under `messages.parse` and are never surfaced raw (FR-007, FR-008). | PASS |
| IV | Independently-Testable Vertical Slices | P1 (auto-nudge on stressed context) is a standalone MVP; P2 (SpO₂/skin-temp/respiration trends) and P3 (bounded/de-dup feed) layer on additively without breaking P1. | PASS |
| V | Explainability & Provenance | Each live `Nudge` records its triggering live signals (`triggered_by`/`anomalies`); the synthesized `ComparisonObject` is inspectable; the existing "chat about this nudge" explains *why raised* from those signals (FR-011). | PASS |
| VI | Reproducibility & Privacy by Default | Live detection is seed/context/timing-reproducible; synthetic data only (no PHI); no new persistence beyond ephemeral `session_state`; key from env (FR-006, SC-003). | PASS |

**Reversal of a prior decision (not a constitution violation).** Phase 2 / the reskin plan locked
"live vitals are presentation-only." This feature intentionally reverses that *product* decision so
live data drives nudges. It does **not** relax any constitutional principle: detection remains
deterministic math *before* the model (Principle I), and the model still consumes only a
pre-computed comparison object. The constitution's Phase-1 "out of scope: real-time streaming" note
is a phase boundary, now superseded by this Phase-3-era feature; the deterministic daily core is
unchanged. No principle is weakened, so no Complexity Tracking entry is required.

**Result**: Constitution Check PASSES.

## Project Structure

### Documentation (this feature)

```text
specs/003-live-auto-nudges/
├── spec.md              # Feature spec (input)
├── plan.md              # This file
├── research.md          # Phase 0 — decisions & rationale
├── data-model.md        # Phase 1 — new anomaly codes/themes, synthesized comparison, live-nudge state
├── quickstart.md        # Phase 1 — how to run & validate the auto-nudge loop
├── contracts/
│   └── live_anomaly.schema.json   # Phase 1 — live-anomaly detection result shape
├── checklists/
│   └── requirements.md  # spec quality checklist (from /speckit-specify)
└── tasks.md             # produced by /speckit-tasks (NOT created here)
```

### Source Code (repository root)

```text
src/wearable_insights/
├── config.py                 # +LIVE_ANOMALY_WINDOW, +LIVE_ANOMALY_MIN_SAMPLES, +NUDGE_COOLDOWN_SECS, +per-signal live deviation dead-bands; reuse ANOMALY_*_PCT / MAX_NUDGES_PER_DAY
├── models.py                 # +AnomalyCode (spo2_low, skin_temp_elevated, resp_rate_elevated, hr_elevated); +AnomalyTheme (vitals) — additive enum values
├── live_anomaly.py           # NEW — rolling live buffer → Anomaly[] (sustained, seeded) + synthesize ComparisonObject from live window (FR-001,3,4,5,6,7)
├── nudges.py                 # EDIT — extend _focused_comparison theme→section map to include the vitals theme (reads heart_health); generate path otherwise unchanged
├── data/live.py              # UNCHANGED — live signal simulator (source of the buffer + anchors)
├── ui/
│   └── live_panel.py         # EDIT — after each sync: detect live anomalies, de-dup + cooldown, generate bounded nudges, surface them; share nudge_set with chat column (FR-002,9,10,13,15,16)
└── app.py                    # EDIT — demote "Simulate Nudge" to hidden/debug fallback; add live_nudge_state to _SS_DEFAULTS + resets; render auto-nudges (FR-002, FR-017)

tests/
├── fixtures/                 # +seeded live buffers (stressed/low-spo2/elevated-temp windows) + a stub generate-fn
├── unit/
│   ├── test_live_anomaly.py  # NEW — sustained → exact anomalies; transient spike → none; reproducible per seed/context (SC-003, SC-005)
│   ├── test_live_comparison.py # NEW — synthesized ComparisonObject fields (current/baseline/pct/tag) correct
│   └── test_live_nudge_dedup.py # NEW — episode de-dup + cooldown re-raise; cap honored (FR-010, FR-016, SC-004)
└── integration/
    └── test_live_auto_nudge.py # NEW — stressed buffer → stress nudge via stubbed LLM, bounded & safety-gated (SC-001, SC-002)
```

**Structure Decision**: Single-project layout, additive. The new deterministic logic
(`live_anomaly.py`) sits beside the existing `anomaly.py`/`nudges.py` and produces the same
`Anomaly`/`ComparisonObject` types, so the existing `nudges.generate_nudge_set` consumes its output
with a one-line theme-map extension. The live loop integration is confined to `ui/live_panel.py`
(detection + de-dup + generation triggered inside the existing fragment) and `app.py` (session
state + button demotion). `data/live.py` and the entire daily-summary pipeline remain unchanged,
preserving the deterministic core and the single nudge-generation/safety codepath.

## Complexity Tracking

> No Constitution Check violations — this section is intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
