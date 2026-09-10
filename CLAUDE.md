<!-- SPECKIT START -->
# Wearable Insights Translation Engine — Agent Context

Active feature: `005-claimguard-integration` (stateless FastAPI sidecar exposing this
engine to ClaimGuard over HTTP — see "Recent changes" below). Authoritative docs live in
`specs/005-claimguard-integration/` (research.md, contracts/rest-api.openapi.json). Prior
phases: `004-slotted-live-baselines`, `003-live-auto-nudges`, `002-nudges-chatbot`,
`001-wearable-insights` baseline — each phase's docs remain in its own `specs/NNN-*/`
directory. The project constitution is in `.specify/memory/constitution.md`. Read the
relevant plan before implementing.

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

- 2026-08-25: Added `005-claimguard-integration` — a stateless FastAPI sidecar
  (`api.py`) exposing the engine to ClaimGuard (Next.js/TypeScript) over HTTP.
  Zero server-side session state: `ProfileRef`/`LiveCursor` reconstruct history and the
  live buffer from a seed tuple, and live-nudge episode/cooldown state round-trips through
  the request/response instead of living in the service. New deterministic modules
  `underwriting.py`, `wellness/streaks.py`, `driving/drowsiness.py`,
  `underwriting_support/attestation.py` — every score is Python-computed; the LLM only
  ever narrates a number it cannot change. `safety.py`'s lexicon is untouched; the
  underwriting narrative ships disabled (`narrative` stays `None`) pending a separate,
  more restrictive safety profile documented in `specs/005-claimguard-integration/
  research.md` (D8). Per-request LLM keys via a `ContextVar` in new `llm/keys.py` — ~6
  changed lines in `llm/google_client.py`/`llm/client.py`, no public signature changes, so
  Streamlit and the pre-existing test suite are unaffected — verified via `pytest`
  (266 passed, 1 pre-existing failure both before and after); 56 new tests added for
  the sidecar bring the suite to 322 passed. Full design record and every deviation from the
  frozen `001` contract: `specs/005-claimguard-integration/research.md`.
- 2026-06-24: Planned `003-live-auto-nudges` — deterministic live-anomaly detection over the
  rolling live buffer (HR/HRV/SpO₂/skin-temp/respiration vs the day's anchor) → synthesized
  ComparisonObject → reuse `nudges.generate_nudge_set` (one codepath/safety gate) → bounded,
  de-duplicated auto-nudges in the live `st.fragment`. Adds `live_anomaly.py`, new AnomalyCode/
  AnomalyTheme values (`vitals`), and de-dup+cooldown session state; daily pipeline untouched.
- 2026-06-18: Initialized Spec Kit artifacts for `001-wearable-insights` (constitution
  v1.0.0; spec, plan, research, data-model, contracts, tasks). Decisions: Claude provider,
  hybrid JSON+narrative output, Streamlit interface, unified incremental scope.
<!-- SPECKIT END -->
