# Phase 1 Data Model: Wearable Insights Translation Engine

**Feature**: `001-wearable-insights` | **Date**: 2026-06-18

Entities are implemented as Pydantic v2 models in `src/wearable_insights/models.py`. The
JSON Schemas in `contracts/` are the design-time source of truth; contract tests assert
the Pydantic models and the schemas stay in sync. Units are fixed and explicit per
Principle III/VI.

## Conventions

- **Units**: durations in minutes; HRV in milliseconds (RMSSD); heart rate in bpm; scores
  are unitless 0–100; steps are counts; stress is a 0–100 score.
- **Dates**: ISO-8601 `YYYY-MM-DD` (date) for daily records; `HH:MM` (local) for bedtime.
- **Missing values**: represented as `null` plus the field name recorded in
  `missing_fields`; never silently defaulted to 0.
- **Rounding**: percentages rounded to 1 decimal; means rounded to the metric's natural
  precision (integers for scores/steps/HR, 1 decimal for HRV/minutes) — fixed so golden
  tests are stable.

## Entity: UserProfile

A synthetic or imported individual and their ordered history.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `user_id` | string | yes | e.g. `usr_2026_dev_01` |
| `age` | int \| null | no | optional metadata |
| `gender` | string \| null | no | free-text / "Non-specified" |
| `records` | `CanonicalDailyRecord[]` | yes | time-ordered ascending by `date`; unique dates |

**Rules**: `records` sorted ascending and date-unique; at least one record.

## Entity: CanonicalDailyRecord

One day for one user. The single normalized shape every input maps to (FR-003).

| Field | Type | Required | Valid range | Notes |
|-------|------|----------|-------------|-------|
| `user_id` | string | yes | — | |
| `date` | date | yes | — | |
| `sleep_duration_minutes` | int \| null | no | 0–1440 | total sleep |
| `sleep_score` | int \| null | no | 0–100 | |
| `deep_sleep_minutes` | int \| null | no | 0–600 | ≤ sleep_duration |
| `rem_sleep_minutes` | int \| null | no | 0–600 | ≤ sleep_duration |
| `bedtime` | time \| null | no | — | local `HH:MM`, for consistency/shift |
| `resting_hr` | int \| null | no | 25–120 | bpm |
| `hrv_rmssd_ms` | number \| null | no | 1–250 | ms |
| `stress_score` | int \| null | no | 0–100 | |
| `steps` | int \| null | no | 0–100000 | |
| `active_minutes` | int \| null | no | 0–1440 | |
| `missing_fields` | string[] | yes | — | names of metrics that were null/absent |
| `invalid_fields` | string[] | yes | — | names of metrics quarantined as out-of-range |

**Validation (FR-004)**: a value outside its valid range is moved to `invalid_fields`
and the stored value set to `null`; an absent value is recorded in `missing_fields`.
Component sleep stages summing above total sleep flag the stages as invalid. Validation
never raises on bad data — it records and continues.

## Entity: BaselineSet

Per-user, per-metric reference values for one analysis date (FR-007).

| Field | Type | Notes |
|-------|------|-------|
| `user_id` | string | |
| `analysis_date` | date | the "current day" |
| `metrics` | map<metric_name, `MetricBaseline`> | one entry per tracked metric |

`MetricBaseline`:

| Field | Type | Notes |
|-------|------|-------|
| `current` | number \| null | current-day value |
| `mean_7d` | number \| null | mean of the prior up-to-7 days |
| `mean_30d` | number \| null | mean of the prior up-to-30 days |
| `weekday_mean` | number \| null | mean of prior same-weekday values |
| `n_days_used` | int | how many history days fed the baseline |
| `low_confidence` | boolean | true when history is short (< 7 days) or baseline undefined |

**Tracked metrics**: `sleep_duration`, `sleep_score`, `deep_sleep`, `rem_sleep`,
`resting_hr`, `hrv`, `stress`, `steps`, `active_minutes`.

## Entity: ComparisonObject

The compact, LLM-facing contract between analysis and inference (FR-009). The LLM
receives **only** this — never raw record tables (Principle I).

| Field | Type | Notes |
|-------|------|-------|
| `user_id` | string | |
| `analysis_date` | date | |
| `sleep` | `ComparisonSection` | sleep metrics |
| `heart_health` | `ComparisonSection` | resting HR, HRV, stress |
| `activity` | `ComparisonSection` | steps, active minutes |
| `candidate_associations` | `CandidateAssociation[]` | may be empty |
| `data_quality` | object | `{ missing_fields[], invalid_fields[], low_confidence: bool }` |
| `schema_version` | string | e.g. `1.0` |

`ComparisonSection` is a map of `metric_name → MetricComparison`:

| Field | Type | Notes |
|-------|------|-------|
| `current_value` | number \| null | current day |
| `baseline_value` | number \| null | the chosen baseline (default 30-day; falls back to 7-day) |
| `percentage_change` | number \| null | signed %, 1 decimal; null if undefined |
| `trend` | enum | `up` \| `down` \| `stable` |
| `evaluation_tag` | enum | `Significantly Elevated` \| `Significantly Depressed` \| `Stable / Within Normal Baseline` \| `Critically Depressed` \| `Critically Elevated` |
| `flags` | string[] | e.g. `below_baseline_sleep`, `reduced_sleep_score` |

**Rules**: `trend` derived from `percentage_change` and the ±15% dead-band (FR-008);
`Critically *` tags reserved for extreme deviations (e.g. |Δ| ≥ 50%); when
`percentage_change` is null, `trend = stable` and `low_confidence` is set.

## Entity: CandidateAssociation

A non-causal co-occurrence produced by a defined rule (FR-010). Never asserts causation
(Principle II).

| Field | Type | Notes |
|-------|------|-------|
| `relation` | string | stable id, e.g. `poor_sleep_and_higher_stress_co_occur` |
| `signals` | string[] | the metrics involved, e.g. `["sleep","stress"]` |
| `description` | string | human-readable, association-framed |
| `kind` | const `"association"` | guards against causal language at the data layer |

**Defined rules (initial set)**:

| Rule | Condition | `relation` |
|------|-----------|-----------|
| R1 | sleep `down` & stress `up` | `poor_sleep_and_higher_stress_co_occur` |
| R2 | steps `down` & sleep `down` | `lower_activity_and_lower_sleep_co_occur` |
| R3 | hrv `down` & stress `up` | `reduced_recovery_and_higher_stress_co_occur` |

Rules are data-driven and extensible without code changes to the engine shape.

## Entity: Insight (and InsightSet)

The user-facing, schema-validated result (FR-013). Produced by the LLM under the
`messages.parse` contract and re-validated by `safety.py`.

`InsightSet`:

| Field | Type | Notes |
|-------|------|-------|
| `insights` | `Insight[]` | 1–3 items |
| `disclaimer` | string | informational-only (non-medical) disclaimer (FR-019) |
| `generated_from` | string[] | union of source signals/trends across insights (explainability, SC-007) |
| `schema_version` | string | e.g. `1.0` |

`Insight`:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `title` | string | yes | short headline |
| `summary` | string | yes | empathetic, physiological **narrative**; associative language only (FR-014, FR-017) |
| `action` | string | yes | **exactly one** concrete action for today (FR-015) |
| `confidence` | enum | yes | `low` \| `medium` \| `high` |
| `source_signals` | string[] | yes | the comparison signals this insight draws on (provenance) |

**Safety constraints enforced post-generation (`safety.py`, FR-014/FR-015/SC-004)**:

- `action` is a single directive (no enumerated multi-step lists).
- `summary` contains no banned diagnostic/causal terms (curated lexicon: e.g.
  "diagnose", "disease", "you have", "causes", "due to" → flagged for review/retry).
- `disclaimer` is present and non-empty.
- `source_signals` ⊆ the signals present in the comparison object (no fabricated provenance).

## Relationships

```text
UserProfile 1──* CanonicalDailyRecord
CanonicalDailyRecord[] ──(trends.py)──> BaselineSet
BaselineSet ──(comparison.py)──> ComparisonObject
ComparisonObject.candidate_associations ──(associations.py)──> CandidateAssociation[]
ComparisonObject ──(llm/insight.py + Claude)──> InsightSet ──(safety.py)──> InsightSet (validated)
```

## State & lifecycle

Stateless and single-pass: a run takes a `UserProfile` (synthetic or CSV-derived) and an
`analysis_date`, flows left-to-right through the relationships above, and yields a
validated `InsightSet`. The `ComparisonObject` may be persisted to a JSON file purely for
inspection/debugging (FR-022); nothing else is stored.
