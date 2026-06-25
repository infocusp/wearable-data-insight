<!-- SPECKIT START -->
# Wearable Insights Translation Engine — Agent Context

Active feature: `003-live-auto-nudges` (live-stream-driven automatic nudges — the rolling
live vitals buffer now feeds a deterministic live-anomaly detector that auto-generates
bounded nudges, replacing the manual "Simulate Nudge" button; reverses the Phase-2 "live is
presentation-only" decision while keeping all math before the model). Authoritative docs live
in `specs/003-live-auto-nudges/` (spec.md, plan.md, research.md, data-model.md, contracts/).
Phase 2 docs remain in `specs/002-nudges-chatbot/` and Phase 1 baseline in
`specs/001-wearable-insights/`; the project constitution is in
`.specify/memory/constitution.md`. Read the plan before implementing.

## What this is

A stateless, single-pass pipeline that turns wearable daily summaries (sleep, recovery/
HRV, stress, activity) into empathetic, interpretable, actionable insights. Deterministic
Python computes features, baselines, trends, and non-causal associations into a compact
**comparison object**; Anthropic **Claude** then translates that object into a
schema-valid **hybrid insight** (structured JSON whose narrative uses cautious,
associative language and ends in exactly one action).

## Active technologies

- **Python 3.11+**
- **anthropic** SDK — insight generation via `messages.parse(output_format=InsightSet)`,
  adaptive thinking (`{"type":"adaptive"}`), `effort="medium"`. Default model
  `claude-sonnet-4-6` (configurable via `WEARABLE_MODEL`). Key from `ANTHROPIC_API_KEY`.
- **pydantic v2** — canonical record / comparison object / insight models (mirror
  `contracts/`)
- **streamlit** — dashboard (primary demo surface); **fastapi + uvicorn** — optional API
- **pytest**, **ruff**, **jsonschema** — tests, lint/format, contract validation

## Project structure (target)

`src/wearable_insights/`: `config.py`, `models.py`, `normalize.py`, `features.py`,
`trends.py`, `comparison.py`, `associations.py`, `safety.py`, `pipeline.py`, `cli.py`,
`app.py`, `api.py`, plus `data/` (synthetic, csv_ingest) and `llm/` (client, prompt,
insight). Tests in `tests/{unit,contract,integration,fixtures}/`.

## Commands

- `python -m wearable_insights.cli --profile recovery_deficit` — MVP run
- `streamlit run src/wearable_insights/app.py` — dashboard
- `pytest` — deterministic suite (no API key needed); `pytest -m live` — live smoke
- `ruff check . && ruff format --check .`

## Non-negotiable rules (from the constitution)

1. **All math before the model** — the LLM never calculates; it only interprets the
   comparison object. Analytics must be deterministic/reproducible per seed.
2. **Associative, never diagnostic** — no medical diagnosis, no causation claims (use "may
   be linked to"); exactly one action per insight; informational-only disclaimer on every
   surface. Enforced by `safety.py` + tests.
3. **Contract-first** — validate canonical records, comparison objects, and LLM output
   against their schemas; never surface raw/invalid model output.
4. **Independently-testable vertical slices** — build in priority order US1→US6; US1 is
   the MVP; later slices are additive.

## Recent changes

- 2026-06-24: Planned `003-live-auto-nudges` — deterministic live-anomaly detection over the
  rolling live buffer (HR/HRV/SpO₂/skin-temp/respiration vs the day's anchor) → synthesized
  ComparisonObject → reuse `nudges.generate_nudge_set` (one codepath/safety gate) → bounded,
  de-duplicated auto-nudges in the live `st.fragment`. Adds `live_anomaly.py`, new AnomalyCode/
  AnomalyTheme values (`vitals`), and de-dup+cooldown session state; daily pipeline untouched.
- 2026-06-18: Initialized Spec Kit artifacts for `001-wearable-insights` (constitution
  v1.0.0; spec, plan, research, data-model, contracts, tasks). Decisions: Claude provider,
  hybrid JSON+narrative output, Streamlit interface, unified incremental scope.
<!-- SPECKIT END -->
