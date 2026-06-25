# Feature Specification: Slotted Time-of-Day Live Baselines

**Feature Branch**: `004-slotted-live-baselines`

**Created**: 2026-06-24

**Status**: Draft

**Input**: User description: "Slotted time-of-day live baselines for anomaly detection — replace the flat per-day resting anchor used by live anomaly detection with a time-of-day slotted baseline (8 × 3-hour slots crossed with weekday/weekend = 16 buckets per signal), comparing the trailing live window against the matching bucket's historical average across 7-day and 30-day horizons. History is synthesized deterministically; sleep stays day-over-day; detection/de-dup/nudge codepaths are unchanged."

## Overview

Today, live-anomaly detection compares the trailing window mean of each live vital
(heart rate, HRV, SpO₂, skin temperature, respiration) against a single **flat** per-day
anchor. That flat anchor has no time-of-day shape, so it produces false alarms during the
naturally elevated parts of the day (afternoon, post-activity) and misses genuine
deviations during naturally calm parts (rest, early morning).

This feature replaces the flat anchor with a **time-of-day slotted baseline**: the day is
divided into 8 fixed 3-hour slots, crossed with a weekday/weekend split, giving 16 buckets
per signal. The trailing live window is compared against the historical average of the
*matching* bucket (current slot + current day-type) across multiple look-back horizons
(7-day and 30-day). Everything downstream — severity tiers, the synthesized comparison
object, de-duplication, cooldown, and nudge generation — is unchanged; only the *source*
of the per-signal anchor changes.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Time-aware anomaly detection (Priority: P1)

As a person wearing the device, when my live vitals drift away from what is normal **for me
at this time of day and this kind of day (weekday vs weekend)**, I receive a nudge; and when
my vitals are merely following their normal daily rhythm, I do **not** receive a false nudge.

**Why this priority**: This is the core value of the feature — circadian-aware comparison is
what removes the afternoon false positives and rest-time misses that the flat anchor causes.
Without it, the rest of the feature has no purpose.

**Independent Test**: With a fixed seed, drive the live buffer with samples that match the
historical bucket average for the current slot → assert **no** anomaly fires. Then drive it
with samples sustained well above/below the bucket average → assert the expected anomaly
fires with the expected severity. Repeat at two different times of day (e.g. a calm morning
slot and a naturally elevated afternoon slot) to show the threshold adapts to the slot.

**Acceptance Scenarios**:

1. **Given** the live buffer's trailing window for a signal sits within the dead-band of the
   current (slot, day-type) bucket average, **When** detection runs, **Then** no anomaly is
   raised for that signal.
2. **Given** the trailing window for a signal is sustained beyond the dead-band of the
   current bucket average, **When** detection runs, **Then** an anomaly is raised with the
   severity tier corresponding to the percentage deviation.
3. **Given** identical raw live values at two different times of day whose bucket averages
   differ, **When** detection runs at each time, **Then** the resulting deviation (and
   whether an anomaly fires) reflects the *slot-specific* baseline, not a single flat anchor.
4. **Given** the same seed and the same simulated clock, **When** detection runs twice,
   **Then** it produces byte-identical anomalies and comparison objects (reproducibility).

---

### User Story 2 - Multi-horizon grounding for the nudge (Priority: P2)

As a reviewer validating a nudge, I want the deviation expressed against both a short-term
(7-day) and a medium-term (30-day) view of the matching time-of-day bucket, so I can see
whether the drift is unusual recently as well as over the longer baseline.

**Why this priority**: Adds interpretive richness and maps cleanly onto the existing
two-window comparison shape, but the feature already delivers value with a single horizon, so
it is additive to P1.

**Independent Test**: For a triggering signal, assert the synthesized comparison object
carries a weekly (7-day) and a monthly (30-day) deviation for the matching bucket, each with
the correct baseline value, percentage change, and evaluation tag.

**Acceptance Scenarios**:

1. **Given** a signal whose trailing window deviates from its bucket average, **When** the
   comparison object is synthesized, **Then** it contains both a 7-day-horizon and a
   30-day-horizon deviation for that signal's current bucket.
2. **Given** a 60-day horizon is configured as informational, **When** detection runs,
   **Then** the 60-day horizon never by itself causes an anomaly to fire.

---

### User Story 3 - Deterministic synthetic history (Priority: P2)

As a developer/demoer, I need a reproducible body of historical intraday data to compute the
slotted bucket averages, because no real multi-day intraday history exists in the system.

**Why this priority**: Required to populate buckets, but it is a supporting capability behind
P1; it is meaningless without the detection that consumes it.

**Independent Test**: Generate the synthetic history twice with the same seed and assert the
per-(signal, slot, day-type) bucket averages are byte-identical; assert every bucket that the
detector can query is populated (no empty bucket for an active signal).

**Acceptance Scenarios**:

1. **Given** a fixed seed and configured history length, **When** the historical bucket
   statistics are built twice, **Then** the two sets of bucket averages are identical.
2. **Given** the configured history length, **When** buckets are built, **Then** every
   (signal, slot, day-type) bucket the detector may look up has at least the minimum number
   of contributing samples required to be considered reliable.

---

### Edge Cases

- **Sparse / empty bucket**: a (slot, day-type) bucket has fewer than the minimum reliable
  sample count for a horizon (e.g. only 1–2 weekend days fall inside a 7-day window). The
  system MUST fall back to a wider horizon (or the all-history bucket) rather than compute a
  deviation from too few samples, and MUST never raise an anomaly off an unreliable bucket.
- **Slot boundary**: the trailing live window straddles two slots (e.g. spans 11:55–12:25
  across a slot boundary). The system MUST assign a single, deterministic slot for the
  comparison (the slot of the most recent sample / current clock), documented and tested.
- **Too few live samples**: the trailing window has fewer than the minimum live samples
  required — existing behavior is preserved (signal is skipped, no anomaly).
- **Missing signal anchor**: a bucket average cannot be derived for a signal (e.g. a signal
  absent from history) — that signal is skipped exactly as a missing flat anchor is today.
- **Day-type at midnight / week boundary**: day-type (weekday vs weekend) is derived
  deterministically from the simulated date; behavior at the Fri→Sat / Sun→Mon transition is
  defined and tested.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST partition the 24-hour day into 8 fixed contiguous 3-hour slots
  and MUST classify each day as weekday or weekend, yielding 16 (slot, day-type) buckets.
- **FR-002**: For each live signal, the system MUST maintain a historical average (and the
  supporting sample count) per (slot, day-type) bucket, per look-back horizon.
- **FR-003**: The system MUST support at least two firing horizons — a 7-day and a 30-day
  look-back — and MAY support a 60-day informational horizon that never by itself triggers an
  anomaly.
- **FR-004**: Live-anomaly detection MUST compare the trailing live window mean of each
  signal against the matching bucket average (current slot + current day-type) instead of a
  flat per-day anchor.
- **FR-005**: The system MUST select the comparison bucket deterministically from the current
  simulated clock and date; given the same seed, clock, and date it MUST select the same
  bucket every time.
- **FR-006**: When the matching bucket for a horizon has fewer than the configured minimum
  reliable sample count, the system MUST fall back to a wider/aggregate baseline and MUST NOT
  raise an anomaly based on an under-populated bucket.
- **FR-007**: The synthesized comparison object MUST express each triggering signal's
  deviation for the matching bucket across the 7-day and 30-day horizons (mapped to the
  existing weekly and monthly comparison windows), preserving the existing object shape so
  the existing nudge and severity logic require no change.
- **FR-008**: Historical intraday data MUST be generated synthetically and deterministically
  (seedable); a given seed and configured history length MUST yield identical bucket
  statistics on every run.
- **FR-009**: Severity tiering, the concerning-direction rules per signal, anomaly de-
  duplication, cooldown, and nudge generation MUST remain behaviorally unchanged; only the
  anchor source changes.
- **FR-010**: Sleep comparison MUST remain day-over-day in the daily pipeline and MUST NOT be
  brought into the slotted live-baseline mechanism.
- **FR-011**: All deviation math MUST be computed in deterministic code before any model is
  invoked; the model MUST continue to receive only the synthesized comparison object, never
  raw live samples or historical tables (constitution Principle I).
- **FR-012**: Anomaly detail/phrasing MUST remain associative (no diagnostic or causal
  language) and reflect the time-of-day basis of the comparison (e.g. "for this time of day"),
  consistent with the existing safety rules (constitution Principle II).
- **FR-013**: Slot count, slot width, horizon lengths, minimum reliable bucket sample count,
  history length, and the random seed MUST be configurable.

### Key Entities *(include if feature involves data)*

- **Time Slot**: one of 8 contiguous 3-hour windows of the day; identified by index/range and
  derived from the clock.
- **Day Type**: weekday or weekend; derived from the simulated date.
- **Baseline Bucket**: the intersection of (signal, slot, day-type, horizon); holds the
  historical average value and the count of contributing samples used to judge reliability.
- **Slotted Baseline Set**: the full collection of buckets the detector queries; replaces the
  flat per-signal anchor dictionary as the source of expected levels.
- **Synthesized Comparison Object**: the existing LLM-grounding object, now carrying per-
  signal deviations against the matching bucket for the 7-day and 30-day horizons.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Live values that follow the normal daily rhythm for the current slot raise zero
  anomalies — specifically, replaying a full synthetic day whose live values track their
  bucket averages produces no nudges (eliminating the flat-anchor false positives).
- **SC-002**: A sustained deviation beyond a signal's dead-band raises exactly one anomaly of
  the expected severity for that signal within the same detection pass.
- **SC-003**: The same raw live reading evaluated in two slots with materially different
  bucket averages yields different deviation outcomes — at least one configuration where the
  reading is "normal" in one slot and "anomalous" in another — demonstrating time-of-day
  sensitivity.
- **SC-004**: Detection and the synthesized comparison object are fully reproducible: two runs
  with the same seed, clock, and date produce identical anomalies and comparison objects.
- **SC-005**: Every (signal, slot, day-type) bucket reachable by the detector is backed by at
  least the configured minimum reliable sample count, or a documented fallback is used; no
  anomaly is ever raised from an under-populated bucket.
- **SC-006**: The existing live-anomaly, nudge, de-dup, and cooldown test suites continue to
  pass with no behavioral changes other than the anchor source.

## Assumptions

- The synthetic history is generated from the existing diurnal/mode live-signal model; it is a
  reasonable stand-in for real wearable history and is acceptable for a synthetic-data PoC
  (constitution Principle VI).
- Slot granularity of 8 × 3-hour slots and a weekday/weekend split (16 buckets) is the agreed
  balance between circadian resolution and per-bucket data density; finer slots or per-weekday
  buckets are explicitly out of scope for this feature.
- The 7-day horizon maps to the existing "weekly" comparison window and the 30-day horizon to
  the existing "monthly" window, so the comparison object shape and downstream code are reused
  rather than extended.
- The 60-day horizon, if implemented, is informational only and never independently triggers a
  nudge.
- Day-type is binary (weekday/weekend); holidays and other calendar nuances are out of scope.
- This feature touches only the live layer; the daily analytics pipeline, including sleep
  comparison, is unchanged.
- Live data remains a deterministic simulation; no real device integration or persistence of
  live history beyond the in-session/synthesized buckets is introduced.
