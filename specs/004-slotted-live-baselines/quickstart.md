# Quickstart Validation: Slotted Time-of-Day Live Baselines

## Prerequisites

```bash
cd /home/dhruv.darda/wearable_analysis
python -m pytest tests/unit/test_slotted_baselines.py tests/unit/test_live_anomaly.py -v
```

No API key required — all tests are deterministic.

## Scenario 1 — No false positive in a calm slot (SC-001)

Build slotted baselines with seed=42, 60 days. At minute=600 (10:00, slot 3, weekday),
construct a flat buffer whose values equal the slot-3 weekday averages. Assert no anomaly fires.

## Scenario 2 — Anomaly fires in elevated slot (SC-002)

Same baselines. Set HR buffer 40% above the slot-3 weekday 7d average. Assert
`hr_elevated` fires with at least `significant` severity.

## Scenario 3 — Time-of-day sensitivity (SC-003)

Same raw HR value evaluated at minute=120 (02:00, slot 0, low overnight HR expected) vs
minute=840 (14:00, slot 4, higher daytime HR expected). Assert the afternoon slot produces
a lower deviation (or no anomaly) while the overnight slot may flag it.

## Scenario 4 — Reproducibility (SC-004)

Build SlottedBaselineSet twice with the same seed. Assert bucket averages are byte-identical.
Run detection twice on the same buffer + baselines. Assert identical anomaly lists.

## Scenario 5 — Multi-horizon comparison object (US2)

Trigger an anomaly. Assert the synthesized ComparisonObject carries both `weekly` (7d) and
`monthly` (30d) WindowComparison fields for the triggering signal, each with
`baseline_value`, `percentage_change`, and `evaluation_tag` populated.

## Scenario 6 — Sparse bucket fallback (edge case)

Configure min_samples=1000 (artificially high). Assert lookup falls back to the all-slot
average, not None, and detection still runs without raising off an empty bucket.

## End-to-end UI check

```bash
streamlit run src/wearable_insights/app.py
```

1. Select "Synthetic" data source. Observe the live signals panel.
2. Switch activity context to "Stressed" — wait 2–3 syncs. Observe a nudge fires.
3. The nudge detail should mention "for this time of day" indicating slotted comparison.
4. Switch back to "Resting" — confirm no spurious nudge fires within a few syncs.
