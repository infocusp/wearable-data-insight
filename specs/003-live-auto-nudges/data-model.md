# Phase 1 — Data Model: Live-Stream-Driven Automatic Nudges

This feature adds **no new top-level entity types**. It extends two enums, reuses the existing
`Anomaly` / `ComparisonObject` / `Nudge` / `NudgeSet` models verbatim, and introduces one
ephemeral session-state structure. All persisted/contract types stay schema-compatible.

## 1. Extended enums (`models.py`) — additive

### `AnomalyCode` (add 4 values)

| New value | Signal | Direction | Maps to theme |
|-----------|--------|-----------|---------------|
| `hr_elevated`        | `hr`         | above anchor | `stress`  |
| `resp_rate_elevated` | `resp_rate`  | above anchor | `vitals`  |
| `spo2_low`           | `spo2`       | below anchor | `vitals`  |
| `skin_temp_elevated` | `skin_temp`  | above anchor | `vitals`  |

Existing `hrv_depressed` (→ `recovery`) is reused for the live HRV-down case. The activity/sleep
codes are untouched and remain owned by the daily pipeline.

### `AnomalyTheme` (add 1 value)

| New value | Covers |
|-----------|--------|
| `vitals`  | SpO₂, skin temperature, respiration rate |

`_SEVERITY_ORDER` and `AnomalySeverity` are unchanged — live anomalies reuse
`moderate`/`significant`/`critical` exactly as the daily ones do.

> **Compatibility**: adding enum members is backward-compatible; existing detection, the daily
> `ComparisonObject`, and persisted chat sessions are unaffected.

## 2. Live `Anomaly` (reused `Anomaly` model, new provenance values)

A live anomaly is an ordinary `Anomaly` instance with:

- `code` ∈ the new/reused codes above
- `theme` ∈ `recovery` | `stress` | `vitals`
- `severity` from `_severity(abs(pct))` against the **existing** thresholds
- `signals` = `[live_signal_key]` (e.g. `["spo2"]`)
- `evaluation_tag` = deterministic label from sign + severity, e.g. `"Significantly Depressed"`
- `detail` = e.g. `"spo2 8.2% below day's expected level (live 30-min trend)"`

**Detection inputs** (not stored on the model, but define the value):

| Field | Meaning | Source |
|-------|---------|--------|
| windowed mean | mean of last `LIVE_ANOMALY_WINDOW` samples for the signal | rolling buffer (`session_state.live_buffer`) |
| anchor | the day's expected level for the signal | `live.live_baselines(today_record)` (+ mode shift) |
| `percentage_change` | `(mean − anchor) / anchor * 100` | computed |

**Validation rules**:
- Require ≥ `LIVE_ANOMALY_MIN_SAMPLES` present in the window, else the signal is skipped (no anomaly).
- `anchor` must be non-zero (it always is for these signals) to compute pct.
- Only the signal's *concerning* direction fires (table in §1); the benign direction yields nothing.
- `abs(pct)` below `ANOMALY_MODERATE_PCT` → no anomaly (dead-band, matches daily behaviour).

## 3. Synthesized `ComparisonObject` (reused model)

Built by `live_anomaly.py` to ground the LLM, shaped exactly like the daily comparison so the
existing nudge path consumes it unchanged:

```text
ComparisonObject(
  user_id        = profile user id,
  analysis_date  = analysis_date,
  heart_health   = {                       # ALL live vitals live here
     "<signal>": MetricComparison(
        current_value = windowed_mean,
        monthly = WindowComparison(
           baseline_value  = anchor,
           percentage_change = pct,
           trend = "up" | "down" | "stable",
           evaluation_tag = "<Significantly|Critically> <Elevated|Depressed>"
                            | "Stable / Within Normal Baseline",
        ),
        flags = [],
     ),
     ...
  },
  sleep = {}, activity = {},                # empty — not live-derived
  candidate_associations = [],              # none synthesized for the live path (kept simple)
  data_quality = DataQuality(),
  schema_version = "1.0",
)
```

- Only signals that produced a (concerning) deviation are included; benign signals are omitted to
  keep the object focused.
- The `monthly` window is populated (not `weekly`) because `anomaly._primary_pct/_primary_tag`
  prefer `monthly` when `baseline_value is not None`. This keeps live anomalies consistent with the
  detector's primary-window logic.

## 4. `nudges._focused_comparison` extension (the one edit)

Current theme→section map keeps `heart_health` for `recovery`/`stress` only. Extend it so the new
`vitals` theme **also** reads from `heart_health`:

```text
heart_health kept when theme in (recovery, stress, vitals)   # was (recovery, stress)
```

No other change to `nudges.py`: grouping by theme, severity ordering, `MAX_NUDGES_PER_DAY` cap,
per-nudge insight generation, and the `safety.check_insight_set` gate all run as-is.

## 5. `LiveNudgeState` (ephemeral, `session_state` only)

Not a Pydantic/contract model — pure in-session bookkeeping for de-dup + cooldown (R5).

| Key | Type | Meaning |
|-----|------|---------|
| `live_nudge_state` | `dict[str, dict]` | per `AnomalyCode.value` → `{ "active": bool, "last_raised_ts": float }` |

State transitions per sync, per detected code:

```text
not in state / not active  → eligible to raise IF (now - last_raised_ts) ≥ NUDGE_COOLDOWN_SECS
                             then: active=True, last_raised_ts=now, emit nudge
active                     → suppress (already raised this episode)
code absent this sync      → active=False (episode ends; eligible to re-raise after cooldown)
```

Reset (set to `{}`) alongside `live_buffer`/`nudge_set` whenever the profile or data source
changes (the existing `_SS_DEFAULTS` reset points in `app.py`).

## 6. New configuration knobs (`config.py`)

| Knob | Default | Purpose |
|------|---------|---------|
| `LIVE_ANOMALY_WINDOW` | `6` | samples in the trailing detection window (≈30 min device time) |
| `LIVE_ANOMALY_MIN_SAMPLES` | `4` | minimum present samples required to evaluate a signal |
| `NUDGE_COOLDOWN_SECS` | `600` | minimum wall-clock gap before re-raising a cleared anomaly (FR-016) |

Reuses without change: `ANOMALY_MODERATE_PCT`, `ANOMALY_SIGNIFICANT_PCT`,
`CRITICAL_THRESHOLD_PCT`, `MAX_NUDGES_PER_DAY`, `LIVE_FETCH_INTERVAL_SECS`,
`DEVICE_SAMPLE_MINUTES`, `LIVE_BUFFER_POINTS`. All overridable via env (existing pattern).

## 7. Provenance (Principle V)

Each live `Nudge` already records `anomalies` (with `signals`) and `triggered_by`
(sorted signal keys). The synthesized `ComparisonObject` is inspectable, and the existing
"💬 Chat about this" path explains *why raised* strictly from those signals — no new wiring needed.
