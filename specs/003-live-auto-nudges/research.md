# Phase 0 — Research & Decisions: Live-Stream-Driven Automatic Nudges

All Technical-Context unknowns are resolved below. Each entry: **Decision · Rationale ·
Alternatives considered.**

## R1 — How to detect a "sustained" live anomaly (vs. transient noise)

**Decision**: Evaluate over a trailing window of the rolling buffer. Compute the **mean of the
last `LIVE_ANOMALY_WINDOW` samples** for each signal (require at least `LIVE_ANOMALY_MIN_SAMPLES`
present), compare that windowed mean to the day's per-signal anchor from `live.live_baselines`,
and compute `percentage_change = (windowed_mean − anchor) / anchor * 100`. Map `abs(pct)` through
the **existing** severity tiers (`ANOMALY_MODERATE_PCT` / `ANOMALY_SIGNIFICANT_PCT` /
`CRITICAL_THRESHOLD_PCT`). Default `LIVE_ANOMALY_WINDOW = 6` samples (= 30 min of simulated device
time at `DEVICE_SAMPLE_MINUTES = 5`).

**Rationale**: A windowed mean is the simplest deterministic low-pass filter — a single noisy spike
(`_NOISE` in `data/live.py`) cannot move the mean past threshold, satisfying FR-005 / SC-005's
"transient spike → no anomaly." Reusing the existing percentage thresholds keeps one severity scheme
(FR-014) and avoids inventing absolute clinical cutoffs (which would risk diagnostic framing).

**Alternatives considered**: (a) Threshold on the single latest sample — rejected: noisy, fires on
transients. (b) Absolute clinical ranges (e.g. SpO₂ < 92%) — rejected: edges toward diagnosis
(Principle II) and the simulator's values aren't clinically calibrated. (c) Slope/regression over
the window — rejected as over-engineered for a seeded demo; mean-vs-anchor is sufficient and
trivially golden-testable.

## R2 — Per-signal direction & theme/code mapping

**Decision**: Direction of concern is per-signal; only the "bad" direction fires an anomaly.

| Live signal | Concerning direction | New/!existing `AnomalyCode` | `AnomalyTheme` |
|-------------|----------------------|------------------------------|----------------|
| hrv         | depressed (below anchor) | `hrv_depressed` (existing) | `recovery` (existing) |
| hr          | elevated (above anchor)  | `hr_elevated` (new)        | `stress` (existing)   |
| resp_rate   | elevated (above anchor)  | `resp_rate_elevated` (new) | `vitals` (new)        |
| spo2        | depressed (below anchor) | `spo2_low` (new)           | `vitals` (new)        |
| skin_temp   | elevated (above anchor)  | `skin_temp_elevated` (new) | `vitals` (new)        |

A single new theme **`vitals`** groups SpO₂ / skin-temp / respiration so the bounded feed
consolidates them sensibly (one "vitals" nudge can cover co-occurring respiratory/temp drift).
HR maps to the existing `stress` theme and HRV to existing `recovery`, so switching to *stressed*
(HRV↓, HR↑, resp↑) naturally produces stress/recovery/vitals anomalies — exactly the US1 behaviour.

**Rationale**: Reuses existing themes where the physiology already fits (stress/recovery), adds the
minimum new surface (one theme, four codes) for the three new signals. Additive enum values don't
break existing detection or the daily pipeline.

**Alternatives considered**: A separate theme per signal (`respiratory`, `temperature`,
`oxygenation`) — rejected: would multiply nudge groups and fight the `MAX_NUDGES_PER_DAY` cap; one
`vitals` theme keeps the feed calm.

## R3 — Grounding the LLM: synthesized ComparisonObject + reuse of `nudges.generate_nudge_set`

**Decision**: From the live window, build a `ComparisonObject` whose `heart_health` dict holds one
`MetricComparison` per triggering signal: `current_value` = windowed mean; `monthly` window =
`WindowComparison(baseline_value=anchor, percentage_change=pct, trend=…, evaluation_tag=…)`. Place
**all** live vitals under `heart_health` (cardio-respiratory vitals). Then call the existing
`nudges.generate_nudge_set(anomalies, synthesized_comparison, generate_fn=…)` unchanged. The **one**
required edit to `nudges.py` is extending `_focused_comparison` so the new `vitals` theme also reads
from `heart_health` (today it only maps `recovery`/`stress` there).

**Rationale**: This honours the user's locked choice — one nudge-generation codepath, one safety
gate. `anomaly._severity`/`_primary_*` already read the `monthly` window, so the synthesized object
flows through `detect_anomalies`-style consumers and through `generate_nudge_set` with no special
casing. `evaluation_tag` is computed deterministically from sign+severity ("Significantly Elevated"
etc.), so the LLM still only *interprets* a pre-computed object (Principle I).

**Alternatives considered**: (a) A parallel `live_nudges.py` with its own prompt/generation —
rejected: violates the "one codepath" decision and duplicates the safety gate. (b) Putting signals
in semantically-split sections (`activity`/`sleep`) — rejected: SpO₂/temp/resp aren't activity or
sleep metrics; `heart_health` is the honest home and needs only the one-line theme-map extension.

## R4 — Surfacing auto-nudges given Streamlit fragment isolation

**Decision**: Run detection + nudge generation **inside** the existing
`@st.fragment(run_every=…)` in `ui/live_panel.py`, and render any newly-raised nudges **within the
fragment** (a compact "⚡ Auto-nudge" area / `st.toast` under the live cards) so they appear without a
full-page rerun. Also append them to the shared `st.session_state.nudge_set` so the existing chat
column's nudge feed and "chat about this nudge" pick them up on the next natural rerun (e.g. when the
user interacts). No `st.rerun()` is forced from the fragment.

**Rationale**: A `run_every` fragment reruns *in isolation* — writing to `session_state` does not
re-render the rest of the page until a normal rerun. Rendering the new nudge inside the fragment
gives immediate visible feedback (SC-001) without re-firing the whole app (which would be wasteful
and could disrupt an open chat). Sharing `nudge_set` keeps auto-nudges fully chat-able like manual
ones, satisfying provenance/continuity with zero changes to the chat layer.

**Alternatives considered**: (a) Force a full `st.rerun()` on each new nudge — rejected: heavy,
re-executes `main()` and flickers the page on every anomaly. (b) Only write to `session_state` and
rely on the next rerun — rejected: the nudge wouldn't visibly appear until the user happens to
interact, failing the "appears automatically within ≤6 syncs" criterion.

## R5 — De-duplication, episodes, and cooldown re-raise (FR-010, FR-016)

**Decision**: Keep a `live_nudge_state` dict in `session_state` mapping each `AnomalyCode` to its
episode status: `{active: bool, last_raised_ts: float}`. On each sync, for each currently-detected
anomaly code: if it is **not active**, it's a new episode → eligible to raise (subject to
cooldown); mark active + stamp time. If it **is active**, suppress (already raised this episode). A
code missing from the current detection for a full sync clears its `active` flag (episode ended).
A cleared code may re-raise on recurrence only once `NUDGE_COOLDOWN_SECS` (default 600s) has elapsed
since `last_raised_ts`; recurrences inside the cooldown are suppressed.

**Rationale**: Directly implements the chosen FR-016 ("re-raise after a cooldown") and FR-010 ("not
duplicated while it persists"). Wall-clock cooldown keyed by code is simple, observable, and bounded;
combined with `MAX_NUDGES_PER_DAY` it keeps the feed calm under rapid context flipping (edge case).

**Alternatives considered**: (a) De-dup purely by `nudge_id` (date+theme) — rejected: can't express
"re-raise later", and theme-level keys would block distinct same-theme signals. (b) Sample-count
cooldown instead of wall-clock — viable, but wall-clock matches the user's "every 15s" mental model
and the demo's real-time feel.

## R6 — Graceful degradation without an API key (FR-013, SC-007)

**Decision**: Detection always runs (pure Python). Nudge generation goes through the existing
`generate_nudge_set`, which already returns an empty/short `NudgeSet` when `generate_fn` is `None`
(no key / SDK absent). The fragment wraps generation in a try/except that, on any error, logs
nothing user-blocking and simply continues refreshing signals. A subtle caption can note "nudges
need an API key" when generation is unavailable.

**Rationale**: Reuses the existing null-safe behaviour in `nudges._load_default_generate_fn` /
`generate_nudge_set`; the live panel must never raise into the fragment and break the auto-refresh.

**Alternatives considered**: Hard-failing or hiding the live panel without a key — rejected: the
live charts are useful on their own and the constitution requires the deterministic layer to work
without a key.

## R7 — Reproducibility scope (Principle VI, SC-003)

**Decision**: Detection reproducibility is asserted against a **fixed seed + context sequence +
sample timing** (the inputs to `live.fetch_latest_sample` / `seed_buffer`). Golden tests build a
buffer deterministically and assert the exact `Anomaly[]`. Wall-clock cooldown is excluded from the
reproducibility claim (it depends on real time) and is tested separately with an injected clock.

**Rationale**: `data/live.py` is already seeded by `device_minute` + mode, so given the same buffer
the detector is pure. Isolating the only non-deterministic input (wall-clock for cooldown) behind an
injectable time source keeps the detector golden-testable and matches the spec's reproducibility
scope note.

**Alternatives considered**: Claiming reproducibility across wall-clock jitter — rejected as
untrue; the spec already scopes reproducibility to seed/context/timing.
