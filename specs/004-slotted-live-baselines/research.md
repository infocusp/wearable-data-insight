# Research: Slotted Time-of-Day Live Baselines

## Key Decisions

### History source
**Decision**: Synthesize 60 days of intraday samples using the existing `data/live.py`
diurnal/mode model.  
**Rationale**: Fits the PoC's synthetic-data constitution (Principle VI); no persistence
required; fully reproducible per seed; immediately available on session start.  
**Alternatives considered**: Real accumulated session history — not viable on day one;
hybrid seeding + accumulation — deferred.

### Slot granularity
**Decision**: 8 × 3-hour slots (00:00–03:00, 03:00–06:00, … 21:00–24:00) crossed with
weekday / weekend = 16 buckets per signal.  
**Rationale**: 3-hour slots capture morning / midday / afternoon / evening circadian
shape. Weekday vs weekend split captures behavioural patterns (active commute vs rest);
with 60 days × 2 samples-per-slot per weekday this gives ~34 samples/bucket — well above
the minimum-3 reliability threshold. Finer slots (1–2h) would under-populate buckets;
per-weekday split (7 day-types) would give only ~8 samples/bucket.

### Comparison horizons
**Decision**: 7-day → `weekly` window, 30-day → `monthly` window in `ComparisonObject`.
60-day is informational only (never triggers an anomaly).  
**Rationale**: Maps directly onto the two existing `WindowComparison` slots; downstream
nudge + LLM code requires no structural change. 7-day horizon is responsive to recent
trends; 30-day is the stable medium-term baseline already used by the daily pipeline.

### Backward compatibility
**Decision**: `detect_live_anomalies` and `synthesize_comparison` accept EITHER a
`SlottedBaselineSet` (new slotted path) OR a flat `dict[str, float]` (legacy path).
**Rationale**: Existing unit tests for Feature 003 can continue to pass the flat dict
without changes; new tests exercise the slotted path explicitly.

### Slot assignment at boundary
**Decision**: The slot is computed from the **current device minute** (the most recent
sample's `minute` field), not the window's start time. This is deterministic and testable.

### Sparse-bucket fallback order
**Decision**: (1) bucket average if count ≥ min_samples; (2) average of all reliable slots
for the same (signal, day_type, horizon); (3) flat resting anchor from `live_baselines()`.
No anomaly is raised from an under-populated bucket — the fallback anchor is used instead.
