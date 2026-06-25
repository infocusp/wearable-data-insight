# Implementation Plan: Slotted Time-of-Day Live Baselines

**Branch**: `004-slotted-live-baselines` | **Date**: 2026-06-24 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/004-slotted-live-baselines/spec.md`

## Summary

Replace the flat per-day resting anchor used by the live-anomaly detector with a
**time-of-day slotted baseline**: 8 × 3-hour slots × weekday/weekend = 16 buckets per
signal. History is synthesized deterministically using the existing diurnal/mode model;
bucket averages per (slot, day-type, horizon) replace the flat anchor dict. Detection,
severity, de-dup, cooldown, and nudge generation are unchanged — only the anchor source
changes. 7d → `weekly` window; 30d → `monthly` window in the synthesized ComparisonObject.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: pydantic v2, streamlit, existing `data/live.py` diurnal model

**Storage**: In-memory per session (synthesized at startup, never persisted)

**Testing**: pytest — unit (deterministic math), no API key needed

**Target Platform**: Linux / Streamlit dashboard

**Project Type**: analytics library + Streamlit app

**Performance Goals**: Bucket build < 500ms at 60 days × 5-min cadence (17,280 samples)

**Constraints**: All math before model (Principle I); reproducible per seed (Principle VI);
associative language only (Principle II); no persistence in analytics layer (Principle VI).

**Scale/Scope**: 5 signals × 16 buckets × 2 horizons = 160 lookup cells per detection pass

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Deterministic Analysis Before Inference | ✅ PASS | All slot/bucket/deviation math in pure Python; LLM only sees synthesized ComparisonObject |
| II. Associative, Never Diagnostic | ✅ PASS | Anomaly detail phrasing updated to say "for this time of day"; no causal claims |
| III. Contract-First Structured Data | ✅ PASS | New `SlottedBaselineSet` type defined; existing ComparisonObject shape reused |
| IV. Independently-Testable Vertical Slices | ✅ PASS | US1 (detection) testable alone; US2 (multi-horizon) additive; US3 (history) supports both |
| V. Explainability & Provenance | ✅ PASS | Anomaly detail records which slot/day-type the comparison is against |
| VI. Reproducibility & Privacy by Default | ✅ PASS | History synthesized with seeded RNG; no real data; stateless per session |

No violations. Complexity Tracking not required.

## Project Structure

### Documentation (this feature)

```text
specs/004-slotted-live-baselines/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code

```text
src/wearable_insights/
├── config.py                        # Add: SLOT_COUNT, SLOT_WIDTH_MINUTES,
│                                    #       BASELINE_HORIZONS, BASELINE_MIN_SAMPLES,
│                                    #       BASELINE_HISTORY_DAYS, BASELINE_SEED
├── data/
│   ├── live.py                      # No changes needed
│   └── slotted_baselines.py         # NEW: slot math + synthetic history + bucket build
├── live_anomaly.py                  # CHANGE: detect_live_anomalies / synthesize_comparison
│                                    #         accept SlottedBaselineSet; anchor lookup from
│                                    #         current slot; multi-horizon comparison object
└── ui/
    └── live_panel.py                # CHANGE: build SlottedBaselineSet once per session;
                                     #         pass to _auto_generate_nudges

tests/
├── unit/
│   ├── test_slotted_baselines.py    # NEW: slot math, bucket build, reproducibility
│   └── test_live_anomaly.py        # EXTEND: slotted anchor path, fallback, SC-003
└── integration/
    └── test_live_auto_nudge.py      # EXTEND: end-to-end with slotted baselines
```

## Implementation Phases

### Phase A — Slotted baseline module (US3, FR-001/002/003/008/013)

New file `data/slotted_baselines.py`:
- `slot_index(minute: int) -> int` — 0-based slot from device minute
- `day_type(weekday: int) -> str` — "weekday" | "weekend"  
- `build_slotted_baselines(record, seed, history_days, horizons, min_samples) -> SlottedBaselineSet`
  - Generates N synthetic days using `live.fetch_latest_sample`
  - Aggregates samples into per-(signal, slot, day_type, horizon) buckets
  - Returns `SlottedBaselineSet` with bucket averages + sample counts
- `lookup_anchor(baselines, signal, slot, day_type, horizon) -> float | None`
  - Returns bucket average if reliable (count ≥ min_samples), else falls back to wider horizon or all-history

Config additions to `config.py`:
```
SLOT_COUNT = 8
SLOT_WIDTH_MINUTES = 180   # 3 hours
BASELINE_HORIZONS = [7, 30]   # days; 60 is informational
BASELINE_MIN_SAMPLES = 3
BASELINE_HISTORY_DAYS = 60
BASELINE_SEED = 42
```

### Phase B — Update live_anomaly.py (US1/US2, FR-004/005/006/007/009/011/012)

- Change `detect_live_anomalies` signature:  
  `anchors: dict[str, float]` → `baselines: SlottedBaselineSet, current_minute: int, current_day_type: str`
- Inside `_evaluate`: compute `slot = slot_index(current_minute)`, then look up anchor via `lookup_anchor`
- Update `_to_anomaly` phrasing: include slot label (e.g. "09:00–12:00, weekday")
- Change `synthesize_comparison`: build `MetricComparison` with both `weekly` (7d) and `monthly` (30d) windows populated from their respective bucket averages

### Phase C — Update live_panel.py (wiring)

- Build `SlottedBaselineSet` once on buffer init (after `profile_dict` is known)
- Store in `st.session_state.live_slotted_baselines`
- Pass `current_minute` (from `st.session_state.live_device_minute`) alongside `baselines` to `_auto_generate_nudges`
- Flat `live.live_baselines()` retained for rendering the signal cards (display only, not detection)

### Phase D — Tests

- `test_slotted_baselines.py`: slot_index boundary, day_type, bucket reproducibility (SC-004), no empty bucket (SC-005), fallback behavior (edge case)
- `test_live_anomaly.py` extensions: slotted path, afternoon slot != morning slot for same raw value (SC-003), no false positive when within bucket mean (SC-001)
