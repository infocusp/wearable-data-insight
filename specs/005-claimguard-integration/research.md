# Research & Decisions — ClaimGuard Integration (Feature 005)

Wraps the existing engine in an HTTP surface so ClaimGuard (Next.js/TypeScript) can use it
across three touchpoints: wellness engagement, underwriting support, and driver-drowsiness
context at motor-claim time.

## D1 — Wrap, don't port

ClaimGuard is TypeScript; this engine is Python. Porting ~2,000 LOC of analytics would fork
the math and duplicate the safety gate. A FastAPI sidecar keeps one implementation.
`fastapi` and `uvicorn` were already pinned in `requirements.txt` and unused, so this added
no dependency.

## D2 — Zero server-side state

The engine is almost entirely pure functions, so the service stores nothing:

| Streamlit `st.session_state` | Replacement |
|---|---|
| `base_profile_dict`, `data_seed` | `ProfileRef` (persona + seed + days + end_date + jitter) |
| `active_comparison` | recomputed per call |
| `live_buffer` (deque) | `LiveCursor`; `seed_buffer()` is pure |
| `live_slotted_baselines` | in-process `lru_cache` (derived — losing it costs latency only) |
| `live_nudge_state` | request field in, response field out |
| chat sessions, agent memory | **not exposed** (see D7) |

Rejected: a Redis/SQLite session store. It would cache values cheaper to recompute, require
sticky sessions, and create a second session identity alongside ClaimGuard's own.

## D3 — `end_date` is required, and `date.today()` is banned from request paths

`slotted_baselines.build_slotted_baselines` and two `pipeline.py` fallbacks call
`date.today()`. In an API context that makes responses change at UTC midnight and differ
between caller and sidecar timezones. `ProfileRef.end_date` is therefore mandatory, and
`tests/integration/test_api_stateless.py` installs a tripwire asserting no handler reaches
`date.today()`.

## D4 — Per-request LLM credentials via `ContextVar`

ClaimGuard holds its Gemini key in the browser and forwards it per request, but `config.py`
reads credentials into module globals at import. `llm/keys.py` adds a `ContextVar` override
consulted by `llm/google_client.py` and `llm/client.py` — ~6 changed lines, no public
signature change, so Streamlit and the existing suite are unaffected.

Wire rules: the key travels in `X-LLM-Api-Key` (**header, never body** — bodies appear in
access logs and FastAPI 422 dumps), access logging is disabled in the image, and there is
**no CORS middleware** because the service is server-to-server only. Thread-isolation is
asserted in `tests/unit/test_api_keys.py`.

## D5 — Measured: the baseline cache is not a performance risk

`build_slotted_baselines` was expected to cost ~2s. Measured at **0.20s** for the default
60-day history (17,280 sample calls, not the ~86k estimated — each call returns all five
signals). Warming all five personas takes **1.1s**, and the cache key uses only the two
record fields `live_baselines()` reads, so personas and dates collapse onto few entries.
The planned "precompute and ship a pickle" fallback is therefore unnecessary.

## D6 — Deviations from the frozen 001 contract

`specs/001-wearable-insights/contracts/rest-api.openapi.yaml` is left untouched.

* `GET /comparison-json` and `POST /generate-insights` are kept as compatibility aliases.
* **`POST /ingest` returns 501.** It presupposes server-side record storage, which
  contradicts D2. Callers send a `ProfileRef` instead and the history is reconstructed.

The new contract is **generated** from the app rather than hand-written, and response models
are the engine's own Pydantic classes, so `models.py` and the published schema cannot drift.
`tests/contract/test_api_openapi.py` fails if they do.

## D7 — Deliberately not exposed

`store.py` and `memory.py` (SQLite chat sessions and LLM-distilled memory of user health
facts) are not surfaced. ClaimGuard already owns conversation state, and a second
differently-persisted store would become a competing source of truth for "who said what" —
undermining the audit trail the underwriting and claims surfaces depend on. The SQLite file
also lives under `data/`, which `.dockerignore` excludes and containers lose.

## D8 — Underwriting ships deterministic-only

`underwriting.py` emits scores, directions, and evidence with **no narrative**
(`narrative is None`). Reasons:

1. The surface is already useful to an underwriter without prose.
2. It requires **zero** change to `safety.py`, so it is reviewable in isolation.
3. `safety.py`'s lexicon bans causal phrasing and only inspects `Insight.summary` — not
   `title` or `action`. An underwriting narrative needs a distinct profile *and* wider field
   coverage; that is a separate, testable change.

The `narrative` / `safety_profile` fields exist from day one so enabling prose later is
purely additive. No decision or price is ever emitted — asserted in
`tests/unit/test_underwriting_signals.py`.

## D9 — Drowsiness is liability context, not fraud evidence

Stated in the module contract and the response disclaimer, and asserted in tests. A fatigue
signal speaks to *how* a collision happened; treating it as dishonesty evidence would use a
health signal against the member.

Calibration is measured, not assumed: two of six contributors are relative to the member's
own baseline, so a *chronically* impaired driver caps near the top of `moderate`, while
`severe` is reachable for an acute collapse against a healthy baseline during a circadian
trough after a long drive. Absolute HRV/resting-HR thresholds would close that gap but are
population-level clinical cutoffs, and adopting them would breach Principle II.

## D10 — Demo fixtures are exported, not seeded live

`scripts/export_demo_fixtures.py` writes `prisma/fixtures/wearable-personas.json` so
`prisma db seed` has no runtime dependency on this service.

It also fixes a trap: `DEFAULT_ANALYSIS_DATE` is a fixed `2026-06-17`, so seeding at that
date makes every "vs 30d" label read as stale history and trips ClaimGuard's 7-day
staleness rule. The exporter re-dates each persona so its final record lands **exactly** on
the demo date. An exact shift (not rounded to whole weeks) is correct: the generator's
weekly cycle is a sinusoid over `day_index`, not the calendar weekday, and same-weekday
baseline selection is shift-invariant — verified — whereas rounding to weeks would leave the
data up to six days stale.
