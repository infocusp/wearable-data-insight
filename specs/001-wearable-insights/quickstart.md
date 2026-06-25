# Quickstart: Wearable Insights Translation Engine

**Feature**: `001-wearable-insights`

This is the developer onboarding + run guide for the Phase 1 PoC. It assumes the source
layout in `plan.md` § Project Structure.

## Prerequisites

- Python 3.11+
- An Anthropic API key (only needed for *live* insight generation; the deterministic test
  suite runs without one)

## 1. Set up the environment

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"            # installs anthropic, pydantic, streamlit, pytest, ruff, ...
```

## 2. Configure secrets

```bash
cp .env.example .env
# edit .env:
#   ANTHROPIC_API_KEY=sk-ant-...
#   WEARABLE_MODEL=claude-sonnet-4-6     # optional; default
```

The key is read from the environment and is never committed or logged (FR-021).

## 3. Run the MVP (User Story 1) — single profile → insight

```bash
# Generate the built-in recovery-deficit snapshot and print the insight
python -m wearable_insights.cli --profile recovery_deficit
```

Expected: a short, empathetic narrative that connects low sleep/HRV/steps with elevated
stress, ending in exactly one action for today, plus the informational-only disclaimer.

To inspect the intermediate (deterministic) comparison object the model received:

```bash
python -m wearable_insights.cli --profile recovery_deficit --dump-comparison comparison.json
```

## 4. Run the dashboard (User Story 4)

```bash
streamlit run src/wearable_insights/app.py
```

Pick a profile and analysis date; the page shows trend cards (sleep duration, sleep
score, HRV, stress, resting HR), the insight card(s), a "generated from" explainability
section, and the disclaimer.

## 5. Bring your own data (User Story 5)

Prepare a CSV with the documented header:

```csv
date,sleep_duration,sleep_score,deep_sleep,rem_sleep,resting_hr,hrv,stress_score,steps,active_minutes
```

Then upload it in the dashboard, or:

```bash
python -m wearable_insights.cli --csv mydata.csv --analysis-date 2026-06-17
```

Missing cells are marked (not fatal); out-of-range values are quarantined and reported.

## 6. Optional REST API (User Story 6)

```bash
uvicorn wearable_insights.api:app --reload
# POST /ingest, POST /generate-insights, GET /comparison-json
# Contract: contracts/rest-api.openapi.yaml
```

## 7. Tests & quality gates

```bash
pytest                 # full deterministic suite — no API key required
pytest -m live         # optional live smoke test — requires ANTHROPIC_API_KEY
ruff check . && ruff format --check .
```

What the suite covers (per the constitution's Quality Gates):

- **Golden analytics**: exact baseline means, percentage changes, trend labels, and
  comparison objects on fixed fixtures (FR-006/007/008/009, SC-006).
- **Reproducibility**: same seed → identical synthetic dataset (FR-001, SC-006).
- **Contract**: canonical record / comparison object / insight validate against
  `contracts/*.schema.json`.
- **LLM boundary**: prompt assembly + output parsing tested with a stubbed client (no
  network).
- **Safety**: insights are associative (no diagnostic/causal phrasing), carry exactly one
  action, and include the disclaimer (FR-014/015/019, SC-004).

## Definition of Done (MVP / User Story 1)

- `python -m wearable_insights.cli --profile recovery_deficit` produces a complete,
  schema-valid insight end-to-end (SC-001, SC-005).
- The deterministic suite passes without an API key.
- Safety checks pass on the generated insight (SC-004).

## Troubleshooting

- **`AuthenticationError` / missing key**: set `ANTHROPIC_API_KEY` in `.env`; the
  deterministic tests don't need it but live generation does.
- **Model output rejected**: the engine retries on schema/safety failure; persistent
  failures surface as a handled error and the comparison object remains inspectable
  (FR-016, FR-022).
- **Slow first call**: model cold start is excluded from the SC-008 target; the stable
  system prompt is prompt-cached so repeat runs in a session are faster.
