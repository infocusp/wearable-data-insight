# Feature Specification: Live-Stream-Driven Automatic Nudges

**Feature Branch**: `003-live-auto-nudges`

**Created**: 2026-06-23

**Status**: Draft

**Input**: User description: "Live-stream-driven automatic anomaly nudges. Replace the manual 'Simulate Nudge' button with automatic nudge generation driven by the live intraday vitals stream. Reverses the prior 'live is presentation-only' decision: the rolling live buffer now feeds a deterministic live-anomaly detector. Activity-context switches (resting/active/stressed) and trends in the live signals must fire relevant anomalies automatically. Extend anomaly detection to cover the already-simulated signals SpO2, skin temperature, and respiration rate. Auto-nudges generate inside the live loop, debounced and bounded by MAX_NUDGES_PER_DAY. Grounding for the LLM nudge writer: synthesize a lightweight comparison-like object and reuse the existing nudge generation + safety-gate path. Must stay deterministic/reproducible per seed and associative + safety-gated; informational disclaimer preserved."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Automatic nudges when activity context changes (Priority: P1)

A person using the dashboard switches their activity context to **Stressed**. Within a
few live syncs, without pressing any button, a stress/recovery nudge appears in the
nudge feed, explaining in cautious, associative language what the live signals suggest
and offering one concrete action. Switching back to **Resting** stops new stress nudges
from being raised.

**Why this priority**: This is the headline behaviour the user asked for — the system
should feel automatic and reactive "like real life," not gated behind a manual button.
It is the smallest slice that demonstrates the whole loop (context → live anomaly →
auto nudge) end to end and replaces the existing manual trigger.

**Independent Test**: Set the activity context to Stressed, let the live feed run for a
few syncs, and confirm a stress-themed nudge appears automatically with a valid title,
summary, exactly one action, and the disclaimer — with no button press.

**Acceptance Scenarios**:

1. **Given** the dashboard is open in Resting context with no active nudges, **When** the
   user switches to Stressed and several live syncs elapse, **Then** a stress/recovery
   nudge is added to the feed automatically without any manual action.
2. **Given** a stress nudge was raised while Stressed, **When** the user switches back to
   Resting, **Then** no additional stress nudges are raised for that context and the
   existing nudge remains visible for review.
3. **Given** the same seed, context sequence, and timing, **When** the live loop runs
   twice, **Then** the same anomalies are detected in the same order (reproducible).

---

### User Story 2 - Trend-based anomalies for SpO₂, skin temperature, and respiration (Priority: P2)

The live feed already streams SpO₂, skin temperature, and respiration rate. The system
now watches these signals' live trend against the day's expected level and raises an
anomaly when a signal drifts meaningfully and persistently (e.g. SpO₂ trending low,
skin temperature elevated, respiration rate elevated), producing an automatic nudge in
the same way as the existing signals.

**Why this priority**: Extends the automatic behaviour to the signals the user
explicitly called out, broadening coverage beyond the original heart-rate / HRV / sleep
/ activity set. Builds on US1's loop, so it is additive and independently demonstrable.

**Independent Test**: Drive the live feed into a context/trend that depresses SpO₂ (or
elevates skin temperature or respiration) for a sustained window, and confirm a
correspondingly themed nudge is raised automatically.

**Acceptance Scenarios**:

1. **Given** SpO₂ trends below its expected level for a sustained window, **When** the
   live loop evaluates the buffer, **Then** a low-SpO₂ anomaly is detected and an
   associated nudge is generated.
2. **Given** skin temperature or respiration rate is elevated for a sustained window,
   **When** the live loop evaluates the buffer, **Then** a correspondingly themed anomaly
   and nudge are produced.
3. **Given** a signal makes a single brief spike that does not persist across the
   evaluation window, **When** the live loop evaluates the buffer, **Then** no anomaly is
   raised (transient noise is suppressed).

---

### User Story 3 - Bounded, non-duplicated automatic feed (Priority: P3)

As the live feed runs, the nudge feed stays calm and trustworthy: at most the configured
daily maximum number of nudges, the most severe themes prioritised, and the same anomaly
is not re-raised on every sync. Each nudge remains traceable to the live signals that
produced it, and the analytics/chat pipeline for the daily summary is unaffected.

**Why this priority**: Without bounding and de-duplication the automatic loop would spam
the feed and erode trust; this slice makes the automatic behaviour production-credible.
It is a refinement on top of US1/US2 rather than a prerequisite for demonstrating them.

**Independent Test**: Run the live feed through several anomalous windows and confirm the
feed never exceeds the daily cap, does not repeat the same nudge each sync, and orders
nudges by severity.

**Acceptance Scenarios**:

1. **Given** more anomaly themes are active than the daily cap allows, **When** nudges are
   generated, **Then** only the cap's worth of nudges are shown, most severe first.
2. **Given** the same anomaly persists across many consecutive syncs, **When** the live
   loop runs, **Then** the nudge is raised once and not duplicated on each subsequent sync.
3. **Given** the live loop is actively generating nudges, **When** the daily-summary chat
   or comparison view is used, **Then** its results are unchanged from before this feature.

---

### Edge Cases

- **No LLM credentials available**: the live loop must not error or block the dashboard;
  it degrades gracefully (no nudge surfaced, deterministic detection still runs).
- **A generated nudge fails the safety gate**: that nudge is silently skipped (consistent
  with existing behaviour), the loop continues, and no unsafe text is surfaced.
- **Rapid context flipping** (e.g. Stressed → Resting → Stressed within a few syncs):
  the system must not produce a burst of duplicate nudges; debouncing/cooldown applies.
- **Anomaly clears then recurs later in the session**: a fresh nudge is re-raised, but only
  after a cooldown has elapsed since the prior nudge for that anomaly (FR-016).
- **Live loop latency**: nudge generation must not freeze the auto-refreshing signal
  cards/charts while the model is being called.
- **Day rollover / clock wrap** during a long-running session: detection and de-duplication
  keys must remain consistent.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST automatically detect anomalies from the live intraday signal
  buffer, without any manual trigger.
- **FR-002**: The system MUST automatically generate and surface nudges in response to
  detected live anomalies, replacing the manual "Simulate Nudge" action as the primary path.
- **FR-003**: Live anomaly detection MUST cover, at minimum, the live signals heart rate,
  HRV, SpO₂, skin temperature, and respiration rate.
- **FR-004**: Changing the activity context (resting / active / stressed) MUST be reflected
  in detection such that a context whose physiology maps to an anomaly (e.g. stressed)
  raises the corresponding anomaly/nudge automatically.
- **FR-005**: Anomalies MUST be detected from a **sustained/trend** deviation over an
  evaluation window, not from a single transient sample, to suppress sensor noise.
- **FR-006**: Live anomaly detection MUST be deterministic and reproducible: the same seed,
  context sequence, and sample timing MUST yield the same anomalies in the same order.
- **FR-007**: The LLM nudge writer MUST be grounded in a synthesized comparison-like object
  derived from the live buffer (current live level vs the day's expected level as baseline),
  reusing the single existing nudge-generation and safety-gate path.
- **FR-008**: Generated nudges MUST remain associative (no diagnosis/causation), MUST end in
  exactly one action, MUST carry the informational disclaimer, and MUST pass the existing
  safety gate; failing nudges MUST NOT be surfaced.
- **FR-009**: The number of automatic nudges surfaced MUST be bounded by the existing daily
  maximum, prioritising the most severe themes.
- **FR-010**: The system MUST NOT duplicate a nudge for the same anomaly while that anomaly
  persists across consecutive live syncs; a nudge for a given anomaly is raised once per
  active episode (see FR-016 for re-raise after the anomaly clears and recurs).
- **FR-011**: Each generated nudge MUST be traceable to the live signal(s) that triggered it
  (provenance preserved).
- **FR-012**: The automatic live loop MUST NOT alter the deterministic daily-summary
  pipeline, the daily comparison object, or the daily-summary chat behaviour.
- **FR-013**: The live loop MUST degrade gracefully when nudge generation is unavailable or
  fails (missing credentials, model error), continuing to refresh signals without surfacing
  errors that block the dashboard.
- **FR-014**: Newly introduced anomaly categories for SpO₂, skin temperature, and respiration
  MUST map to appropriate themes and severity consistent with the existing severity scheme.
- **FR-015**: The user MUST be able to see the current activity context and understand that
  nudges are generated automatically from the live feed (clear, non-misleading framing).

- **FR-016**: After a live anomaly clears (its signal returns to normal) and later recurs in
  the same session, the system MUST re-raise a fresh nudge for it, but only once a cooldown
  period has elapsed since the previous nudge for that anomaly; recurrences within the cooldown
  MUST be suppressed. All re-raises remain bounded by the daily cap (FR-009).
- **FR-017**: The manual "Simulate Nudge" control MUST be retained as a hidden/debug fallback
  (still functional for demos) while automatic live-driven nudges become the primary path.

### Key Entities *(include if feature involves data)*

- **Live Anomaly**: A deterministically detected, sustained deviation of a live signal from
  its expected level over an evaluation window. Attributes: signal(s), theme, severity,
  direction, the deviation that triggered it, detection timestamp. Distinct from the existing
  daily-summary anomaly in that its baseline is the day's expected level, not a 30-day history.
- **Synthesized Comparison View**: A lightweight, comparison-shaped grounding object built
  from the live buffer (live value vs the day's expected level) so the existing nudge writer
  can consume it unchanged.
- **Live Nudge**: A bounded, safety-gated, associative insight generated from a live anomaly,
  carrying provenance to its triggering live signals and the standing disclaimer.
- **Activity Context**: The resting / active / stressed selector that shifts the expected
  physiology of the live signals and therefore influences which anomalies fire.
- **Nudge Feed State**: The session-scoped record of which anomalies have already produced a
  nudge (for de-duplication) and the bounded set of nudges currently surfaced.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After switching to the Stressed context, a relevant nudge appears
  automatically within a small, bounded number of live syncs (target: ≤ 6 syncs) with no
  manual action.
- **SC-002**: 100% of surfaced nudges are associative, end in exactly one action, and show
  the disclaimer (zero safety-gate escapes).
- **SC-003**: Live anomaly detection is reproducible: repeated runs with the same seed,
  context sequence, and timing produce identical anomalies in identical order (byte-identical
  detection result).
- **SC-004**: The automatic feed never exceeds the configured daily nudge cap and never shows
  the same anomaly's nudge more than once while it persists.
- **SC-005**: All five live signals (heart rate, HRV, SpO₂, skin temperature, respiration)
  can each independently trigger an automatic nudge under an appropriate trend.
- **SC-006**: The deterministic daily-summary pipeline and its tests are unchanged — the
  existing deterministic suite stays green and the daily comparison/chat results are identical
  to before the feature.
- **SC-007**: With no model credentials configured, the dashboard's live signals keep
  refreshing and no blocking error is shown (graceful degradation).

## Assumptions

- The live signal simulator already streams heart rate, HRV, SpO₂, skin temperature, and
  respiration rate at an intraday cadence with activity-context shifts; this feature consumes
  that stream rather than introducing new sensors.
- "The day's expected level" for a signal is the per-signal anchor the live feed already
  derives for the current day; this serves as the deterministic baseline for live anomalies.
- This feature deliberately reverses the earlier Phase-2 decision that "live vitals are
  presentation-only." The reversal is compatible with the constitution because live detection
  stays deterministic/seed-reproducible (Principle I) and the model still receives a
  pre-computed, comparison-shaped object — never raw tables — and remains associative and
  safety-gated (Principle II). The daily-summary deterministic core remains untouched.
- The existing daily nudge cap and severity thresholds are reused; live detection introduces
  new signal categories but not a new severity scheme.
- Reproducibility is asserted against a fixed seed, context sequence, and sample timing; it is
  not claimed across arbitrary wall-clock refresh jitter.
- The conversational layer (chat about a nudge) continues to work for auto-generated nudges
  the same way it does for the current manual ones.
