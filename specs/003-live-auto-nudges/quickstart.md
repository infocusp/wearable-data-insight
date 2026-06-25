# Quickstart — Live-Stream-Driven Automatic Nudges

How to run and validate the feature end to end. Implementation details live in `tasks.md`;
contracts in `contracts/` and `data-model.md`.

## Prerequisites

- Python 3.11+, deps installed (`pipenv install` / project's existing setup).
- For nudge *text* generation: `ANTHROPIC_API_KEY` in the environment. Without it, the live
  signals + deterministic anomaly detection still run; only the LLM-written nudge text is skipped
  (graceful degradation — FR-013 / SC-007).

## Run the dashboard

```bash
streamlit run src/wearable_insights/app.py
```

## Validate the user stories

### US1 — Auto-nudge on activity-context switch (P1, the MVP)

1. Open the dashboard; the **Live signals** panel auto-syncs every ~15s.
2. In the panel's **Activity context** selector, switch to **Stressed**.
3. **Expected**: within ≤ 6 syncs (SC-001), a stress/recovery nudge appears automatically —
   no button press — with a title, summary, exactly one action, and the disclaimer (SC-002).
4. Switch back to **Resting** → no *new* stress nudges are raised; the existing one stays visible.
5. Click **💬 Chat about this** on the auto-nudge → it is chat-able exactly like a manual nudge.

### US2 — SpO₂ / skin-temp / respiration trend anomalies (P2)

1. Drive a context/trend that depresses SpO₂ (or elevates skin temp / respiration) for a sustained
   window (≈30 min device time = ~`LIVE_ANOMALY_WINDOW` syncs).
2. **Expected**: a `vitals`-themed nudge is raised automatically (SC-005), each of the five signals
   able to trigger independently under the right trend.
3. A single brief spike that does not persist across the window → **no** anomaly (FR-005).

### US3 — Bounded, de-duplicated feed (P3)

1. Let several anomalous windows occur.
2. **Expected**: the feed never exceeds `MAX_NUDGES_PER_DAY`, most-severe themes first (FR-009);
   a persisting anomaly is **not** re-raised every sync (FR-010); after it clears and recurs, it
   re-raises only once `NUDGE_COOLDOWN_SECS` has elapsed (FR-016).
3. Use the daily-summary comparison/chat → unchanged from before this feature (FR-012 / SC-006).

## Deterministic checks (no API key)

```bash
pytest tests/unit/test_live_anomaly.py        # sustained → exact anomalies; spike → none; reproducible
pytest tests/unit/test_live_comparison.py     # synthesized ComparisonObject fields correct
pytest tests/unit/test_live_nudge_dedup.py    # episode de-dup + cooldown re-raise; cap honored
pytest tests/integration/test_live_auto_nudge.py   # stressed buffer → stress nudge via stubbed LLM
pytest                                         # full deterministic suite stays green (SC-006)
ruff check . && ruff format --check .
```

Reproducibility (SC-003): building the same seeded buffer + context sequence twice yields identical
`Anomaly[]` in identical order. Cooldown timing is tested with an injected clock, not wall-clock.

## Optional live smoke

```bash
pytest -m live    # one real auto-nudge generation via Claude (requires ANTHROPIC_API_KEY)
```

## Confirm the deterministic core is untouched

```bash
# Live detection imports the buffer + anchors, but the daily pipeline must not depend on it:
grep -rn "live_anomaly" src/wearable_insights/pipeline.py src/wearable_insights/comparison.py
# (expected: no matches — daily pipeline is independent of the live layer)
```
