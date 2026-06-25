---
description: "Task list for Live-Stream-Driven Automatic Nudges"
---

# Tasks: Live-Stream-Driven Automatic Nudges

**Input**: Design documents from `/specs/003-live-auto-nudges/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/live_anomaly.schema.json

**Tests**: Included — the constitution (Quality Gates) mandates unit/golden tests for the
deterministic layers (`live_anomaly` detection, synthesized comparison, de-dup/cooldown).

**Organization**: Grouped by user story (US1 P1 → US2 P2 → US3 P3) so each is an independently
testable, demoable increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete tasks)
- **[Story]**: US1 / US2 / US3 (Setup, Foundational, Polish carry no story label)

## Path Conventions

Single project: `src/wearable_insights/`, `tests/` at repo root (per plan.md Structure Decision).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Config knobs the detector and live loop depend on.

- [X] T001 Add live-detection config knobs to [src/wearable_insights/config.py](../../src/wearable_insights/config.py): `LIVE_ANOMALY_WINDOW` (default 6), `LIVE_ANOMALY_MIN_SAMPLES` (default 4), `NUDGE_COOLDOWN_SECS` (default 600), each env-overridable following the existing pattern; reuse `ANOMALY_*_PCT`, `CRITICAL_THRESHOLD_PCT`, `MAX_NUDGES_PER_DAY`, `DEVICE_SAMPLE_MINUTES`, `LIVE_BUFFER_POINTS` unchanged.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Detector skeleton + synthesized-comparison builder shared by all stories. No
story-specific signal rules yet (those land per story).

- [X] T002 Create [src/wearable_insights/live_anomaly.py](../../src/wearable_insights/live_anomaly.py) skeleton: a `_SignalRule` table (signal key, concerning direction, AnomalyCode, AnomalyTheme — empty for now, filled per story), `_windowed_mean(buffer, key, window, min_samples)` helper, and `_severity`/`evaluation_tag` reuse from `anomaly.py` (import `_severity` or replicate the tier mapping). Pure functions, no Streamlit import.
- [X] T003 In [src/wearable_insights/live_anomaly.py](../../src/wearable_insights/live_anomaly.py) add `synthesize_comparison(detections, anchors, user_id, analysis_date) -> ComparisonObject`: build one `MetricComparison` per triggering signal under `heart_health` with `current_value=windowed_mean`, `monthly=WindowComparison(baseline_value=anchor, percentage_change=pct, trend, evaluation_tag)`; `sleep`/`activity`/`associations` empty (per data-model §3).
- [X] T004 Add `detect_live_anomalies(buffer, anchors, mode, *, window, min_samples) -> list[Anomaly]` to [src/wearable_insights/live_anomaly.py](../../src/wearable_insights/live_anomaly.py): iterate the rule table, compute windowed mean vs anchor, apply dead-band + direction + severity, return ordered `Anomaly[]` (rule-declaration order for reproducibility). Rule table still empty → returns `[]`; signal rules added in US phases.
- [X] T005 [P] Add the synthesized-comparison contract test [tests/contract/test_live_anomaly_schema.py](../../tests/contract/test_live_anomaly_schema.py): validate a sample live `Anomaly` against [contracts/live_anomaly.schema.json](contracts/live_anomaly.schema.json) using `jsonschema`.

**Checkpoint**: detector + comparison builder importable and unit-constructible; no signals fire yet.

---

## Phase 3: User Story 1 — Auto-nudge on activity-context switch (Priority: P1) 🎯 MVP

**Goal**: Switching the live panel to **Stressed** automatically raises a stress/recovery nudge
(HR↑ / HRV↓) within a few syncs, with no button press, fully safety-gated.

**Independent Test**: Build a seeded stressed buffer, run the loop, confirm a stress-themed nudge
appears automatically (valid title/summary/one-action/disclaimer).

- [X] T006 [US1] Add `hr_elevated` to `AnomalyCode` in [src/wearable_insights/models.py](../../src/wearable_insights/models.py) (additive enum value; `hrv_depressed`/themes already exist).
- [X] T007 [US1] Populate the `live_anomaly.py` rule table with the HR→stress (elevated) and HRV→recovery (depressed) rules so a stressed buffer fires both.
- [X] T008 [US1] Extend `_focused_comparison` in [src/wearable_insights/nudges.py](../../src/wearable_insights/nudges.py): keep `heart_health` for `stress`/`recovery` (already present) — verify HR/HRV signals flow through; no other change to the generation path.
- [X] T009 [US1] Wire detection + generation into the live fragment in [src/wearable_insights/ui/live_panel.py](../../src/wearable_insights/ui/live_panel.py): after appending each sample, call `detect_live_anomalies(...)`, and for new anomalies `synthesize_comparison(...)` → `nudges.generate_nudge_set(anomalies, synthesized, generate_fn=...)`; append results to `st.session_state.nudge_set` and render them in-place (compact auto-nudge area / `st.toast`). Wrap generation in try/except so the fragment never breaks the auto-refresh (FR-013).
- [X] T010 [US1] Add `nudge_set` sharing + `live_nudge_state` defaults to `_SS_DEFAULTS` and the profile/source reset points in [src/wearable_insights/app.py](../../src/wearable_insights/app.py) so auto-nudges appear in the existing chat-column feed and reset on profile change.
- [X] T011 [P] [US1] Add seeded fixture for a stressed live buffer + a stub generate-fn in [tests/fixtures/](../../tests/fixtures/) (returns a canned valid `InsightSet`, no API key).
- [X] T012 [P] [US1] Unit test [tests/unit/test_live_anomaly.py](../../tests/unit/test_live_anomaly.py): stressed buffer → exact `hr_elevated`+`hrv_depressed` anomalies in declared order; building the same seeded buffer twice yields identical results (SC-003); a single-sample spike does not fire (FR-005).
- [X] T013 [P] [US1] Unit test [tests/unit/test_live_comparison.py](../../tests/unit/test_live_comparison.py): `synthesize_comparison` sets `current_value`, `monthly.baseline_value`, `percentage_change`, and the correct `evaluation_tag` (sign+severity).
- [X] T014 [US1] Integration test [tests/integration/test_live_auto_nudge.py](../../tests/integration/test_live_auto_nudge.py): stressed buffer → `generate_nudge_set` (stub fn) → a stress/recovery nudge that is bounded, single-action, disclaimer-bearing, safety-gated (SC-001, SC-002).

**Checkpoint**: US1 is a shippable MVP — stressed context auto-nudges end to end.

---

## Phase 4: User Story 2 — SpO₂ / skin-temp / respiration trend anomalies (Priority: P2)

**Goal**: The already-streamed SpO₂, skin temperature, and respiration signals can each raise an
automatic `vitals`-themed nudge from a sustained trend.

**Independent Test**: Drive a sustained low-SpO₂ (or high skin-temp / high respiration) window and
confirm a `vitals` nudge appears automatically; a brief spike does not.

- [X] T015 [US2] Add `spo2_low`, `skin_temp_elevated`, `resp_rate_elevated` to `AnomalyCode` and `vitals` to `AnomalyTheme` in [src/wearable_insights/models.py](../../src/wearable_insights/models.py) (additive).
- [X] T016 [US2] Add the SpO₂(down)/skin-temp(up)/respiration(up) rules → `vitals` theme to the `live_anomaly.py` rule table (per data-model §1/R2).
- [X] T017 [US2] Extend `_focused_comparison` in [src/wearable_insights/nudges.py](../../src/wearable_insights/nudges.py) so the `vitals` theme also reads from `heart_health` (the one documented edit; data-model §4).
- [X] T018 [P] [US2] Add seeded fixtures for low-SpO₂ / elevated-skin-temp / elevated-respiration buffers in [tests/fixtures/](../../tests/fixtures/).
- [X] T019 [P] [US2] Extend [tests/unit/test_live_anomaly.py](../../tests/unit/test_live_anomaly.py): each vitals signal independently fires its code/theme under a sustained trend (SC-005); benign direction yields nothing; transient spike suppressed.
- [X] T020 [US2] Extend [tests/integration/test_live_auto_nudge.py](../../tests/integration/test_live_auto_nudge.py): a low-SpO₂ window produces a `vitals` nudge via the stub fn, safety-gated.

**Checkpoint**: all five live signals can independently trigger auto-nudges.

---

## Phase 5: User Story 3 — Bounded, de-duplicated automatic feed (Priority: P3)

**Goal**: The auto-feed stays calm and trustworthy: ≤ `MAX_NUDGES_PER_DAY`, severity-ordered, no
duplicate per active episode, cooldown re-raise after clear/recur; daily pipeline untouched;
manual button demoted.

**Independent Test**: Run through several anomalous windows; confirm cap, no per-sync duplicates,
cooldown re-raise (with injected clock), and an unchanged daily-summary chat/comparison.

- [X] T021 [US3] Implement de-dup + cooldown in [src/wearable_insights/live_anomaly.py](../../src/wearable_insights/live_anomaly.py) (or a small `live_nudge_state` helper): `filter_new_anomalies(detections, state, now, cooldown) -> (new_anomalies, updated_state)` per the state machine in data-model §5; clock injectable for tests.
- [X] T022 [US3] Apply the filter in [src/wearable_insights/ui/live_panel.py](../../src/wearable_insights/ui/live_panel.py): only generate nudges for `new_anomalies`, persist updated `live_nudge_state`, and rely on `NudgeSet`'s existing cap (severity-ordered via `consolidate_nudge_groups`).
- [X] T023 [US3] Demote the **🔔 Simulate Nudge** control in [src/wearable_insights/app.py](../../src/wearable_insights/app.py) to a hidden/debug fallback (e.g. behind a debug expander), keeping it functional (FR-017); update the "Run Simulate Nudge…" caption text in `_render_nudge_history`.
- [X] T024 [P] [US3] Unit test [tests/unit/test_live_nudge_dedup.py](../../tests/unit/test_live_nudge_dedup.py): persisting anomaly raised once per episode; cleared+recurred raises again only after `NUDGE_COOLDOWN_SECS` (injected clock); within-cooldown recurrence suppressed; cap honored (FR-010, FR-016, SC-004).
- [X] T025 [P] [US3] Test that the daily pipeline is independent: `grep`-style assertion or import test confirming `pipeline.py`/`comparison.py` do not import `live_anomaly`/`data.live` (SC-006, FR-012).

**Checkpoint**: feed is bounded, de-duplicated, cooldown-aware; daily core proven untouched.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T026 [P] Add a brief "nudges need an API key" caption path in [src/wearable_insights/ui/live_panel.py](../../src/wearable_insights/ui/live_panel.py) when generation is unavailable (graceful degradation, SC-007).
- [X] T027 [P] Run `ruff check . && ruff format --check .` and fix findings in the new/edited files.
- [X] T028 Run the full `pytest` suite; confirm the pre-existing deterministic suite stays green (SC-006) and the new tests pass.
- [X] T029 [P] Manual validation per [quickstart.md](quickstart.md): `streamlit run src/wearable_insights/app.py`, switch to Stressed, confirm an auto-nudge within ≤6 syncs and that it is chat-able.

---

## Dependencies & Execution Order

- **Setup (T001)** → **Foundational (T002–T005)** → **US1 (T006–T014)** → **US2 (T015–T020)** → **US3 (T021–T025)** → **Polish (T026–T029)**.
- US1 is the MVP and is independently shippable after Phase 3.
- US2 depends only on the Foundational detector/comparison + its own enum/rule additions (additive to US1).
- US3 refines the loop from US1/US2; it does not block demoing US1 or US2.

### Parallel opportunities

- Foundational: T005 ∥ T002–T004 (different files).
- US1: T011, T012, T013 run in parallel (fixtures + two unit files); T006/T007 precede T012.
- US2: T018, T019 parallel; T015–T017 precede them.
- US3: T024, T025 parallel after T021–T023.
- Polish: T026, T027, T029 parallel; T028 after code-complete.

## Implementation Strategy

**MVP = Phase 1 + Phase 2 + Phase 3 (US1).** Ship the stressed-context auto-nudge first, demo it,
then layer US2 (vitals signals) and US3 (bounded/de-dup feed) additively. Each phase ends at a
green-test checkpoint and leaves the daily-summary pipeline untouched.
