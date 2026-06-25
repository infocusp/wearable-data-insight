# Data Model: Slotted Time-of-Day Live Baselines

## Entities

### SlottedBaselineSet

In-memory per-session object holding pre-aggregated historical bucket statistics.
Never persisted, never serialised to JSON, never seen by the LLM.

| Field | Type | Description |
|---|---|---|
| averages | dict[(signal, slot, day_type, horizon_days) → float] | Mean signal value for each bucket |
| counts | dict[(signal, slot, day_type, horizon_days) → int] | Number of samples contributing |
| flat_anchors | dict[signal → float] | Fallback flat resting values from live_baselines() |
| horizons | tuple[int, ...] | Active horizons, e.g. (7, 30) |
| min_samples | int | Minimum count for a bucket to be considered reliable |

### TimeSlot

Derived value; never stored independently.

| Field | Derivation |
|---|---|
| index (0–7) | `(minute % 1440) // 180` |
| label | `"HH:00–HH:00"` for display and anomaly detail |
| day_type | `"weekday"` if weekday < 5 else `"weekend"` |

### Baseline Bucket (logical)

One cell in SlottedBaselineSet addressed by (signal, slot_index, day_type, horizon_days).

Reliability rule: a bucket is **reliable** iff `counts[key] >= min_samples`.
Unreliable buckets use the fallback chain; they never directly trigger an anomaly.

## Updated ComparisonObject shape (live path)

The existing `ComparisonObject.heart_health[signal]` MetricComparison now carries:

| Window field | Source |
|---|---|
| `weekly` | 7-day horizon bucket for current (slot, day_type) |
| `monthly` | 30-day horizon bucket for current (slot, day_type) |

All other fields (`sixty_day`, `ninety_day`, `weekday`) remain empty/default for the
live path. The daily pipeline is untouched.

## Bucket population formula

```
samples_per_bucket ≈ (history_days / horizon_days) * (slot_width_minutes / sample_step_minutes) * (horizon_days / 7 * (5 or 2))
```

At 60-day history, 5-min sample step, 7-day horizon:
- Weekday bucket: ~5 weekdays × 36 samples/slot = ~180 samples
- Weekend bucket: ~2 weekend days × 36 samples/slot = ~72 samples

Both are well above min_samples=3.

## Lookup fallback chain

```
1. (signal, slot, day_type, horizon)          reliable? → use it
2. avg of all reliable slots (signal, *, day_type, horizon) → use it  
3. flat_anchors[signal]                        → use it
4. None                                        → signal skipped (as before)
```
