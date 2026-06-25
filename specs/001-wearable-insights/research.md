# Phase 0 Research: Wearable Insights Translation Engine

**Feature**: `001-wearable-insights` | **Date**: 2026-06-18

This document records the technical decisions behind the plan, the alternatives
considered, and the rationale. There are no open `NEEDS CLARIFICATION` items — the four
material ambiguities in the source plan were resolved with the stakeholder (see the
Clarifications section of `spec.md`).

## D1. LLM provider and model

- **Decision**: Anthropic Claude via the official `anthropic` Python SDK. Default model
  `claude-sonnet-4-6`, exposed via config (`WEARABLE_MODEL`) so it can be swapped (e.g. to
  `claude-sonnet-4-6` for cheaper/faster runs).
- **Rationale**: The insight task is a nuanced, physiologically-coherent, empathetic
  translation that benefits from a strong reasoning model; Sonnet 4.6 is the most capable
  current default. Keeping the model id in config lets a high-volume/cost-sensitive demo
  drop to Sonnet without code changes.
- **Alternatives considered**: OpenAI gpt-4o (as written in the source plan) — rejected
  per stakeholder decision to standardize on Claude. A provider-abstracted client —
  deferred as unnecessary complexity for a single-provider Phase 1 (Constitution: "No
  other LLM provider is introduced in Phase 1").

## D2. Structured / schema-valid insight output

- **Decision**: Use `client.messages.parse(..., output_format=InsightSet)` with a
  Pydantic model for the insight payload, so the model is constrained to valid JSON and
  the SDK returns a typed, validated object (`response.parsed_output`).
- **Rationale**: Directly satisfies FR-013/FR-016/SC-005 (schema-valid output, reject
  invalid). The Pydantic model doubles as runtime validation and as the source of truth
  mirrored by `contracts/insight.schema.json`.
- **Alternatives considered**: Raw `output_config={"format": {"type":"json_schema", ...}}`
  + manual `json.loads` — viable but more boilerplate than `messages.parse`. Free-text
  Markdown + regex extraction — rejected: not parseable for the dashboard and violates
  Principle III. Assistant-message prefill to force JSON — rejected: prefills return 400
  on Sonnet 4.6.

## D3. Thinking and effort settings

- **Decision**: Adaptive thinking (`thinking={"type": "adaptive"}`) with
  `output_config={"effort": "medium"}` as the starting point for insight generation.
- **Rationale**: Adaptive thinking lets the model reason about the physiological
  interplay without a fixed budget; `medium` effort balances quality and cost/latency for
  an interactive demo (SC-008). `budget_tokens` is removed on Sonnet 4.6, so adaptive is
  the correct mechanism.
- **Alternatives considered**: `effort: "high"` — held in reserve if insight quality is
  insufficient; thinking disabled — rejected, the interplay reasoning is the point.

## D4. Determinism of the analytics layers

- **Decision**: All math in plain Python over ordered records; fixed rounding rules;
  no wall-clock or randomness in the analysis path (randomness confined to the seeded
  synthetic generator). The comparison object is the deterministic contract; golden-fixture
  tests assert exact values.
- **Rationale**: Principle I + FR-011 + SC-006 require byte-identical comparison objects
  per seed/config. Determinism also makes the LLM boundary independently testable.
- **Alternatives considered**: Letting the LLM compute deviations — explicitly rejected by
  the constitution and the source plan's "BAD EXAMPLE" anti-pattern.

## D5. Trend-label thresholds

- **Decision**: Percentage deviation vs baseline with a ±15% dead-band → `stable`;
  `> +15%` → `up`, `< -15%` → `down`. The "good vs bad" interpretation of a direction is
  left to the LLM narrative and the flags, not encoded as a value judgment in the label.
- **Rationale**: Matches the source plan's categorization rule and FR-008; a single
  documented threshold keeps trends explainable. Per-metric thresholds are a possible
  Phase-2 refinement.
- **Alternatives considered**: z-score / stdev-band thresholds — more statistically
  principled but overkill for a PoC and harder to explain to reviewers; deferred.
- **Edge rule**: when a baseline is ~0 or unavailable, percentage change is undefined →
  label `stable` with a reduced-confidence flag rather than dividing by zero.

## D6. Synthetic data generation

- **Decision**: A seeded generator (`random.Random(seed)` / `numpy` Generator) producing
  4 profiles (healthy-consistent, poor-sleep week, low-activity, recovery-decline) over a
  configurable window (default 90 days), plus the explicit "recovery deficit" snapshot
  used for the P1 demo. Profiles are parameterized by per-metric mean/variance and
  trend drift.
- **Rationale**: FR-001/FR-002 + Principle VI (reproducibility). A given seed yields a
  given dataset, enabling golden tests and stable demos.
- **Alternatives considered**: Hand-authored static JSON only — insufficient for trend
  testing across 90 days; static fixtures are kept additionally for the P1 snapshot and
  golden tests.

## D7. Insight payload shape (hybrid JSON + cautious narrative)

- **Decision**: `InsightSet = { insights: [ Insight ], disclaimer, generated_from }`,
  where `Insight = { title, summary (narrative), action (exactly one), confidence
  (low|medium|high), source_signals: [string] }`. The `summary` carries the empathetic,
  physiological narrative in associative language; `source_signals` powers explainability.
- **Rationale**: Resolves the source plan's contradiction (narrative vs strict JSON) per
  the stakeholder's "hybrid" choice — parseable for the dashboard yet human-friendly, and
  carries provenance (Principle V).
- **Alternatives considered**: Pure Markdown narrative (not parseable; weak provenance);
  pure associative JSON with no narrative (less vivid). Both rejected in favor of hybrid.

## D8. Safety enforcement (associative, non-diagnostic)

- **Decision**: Defense in depth — (a) a strict system prompt with explicit rules and a
  good/bad example pair; (b) `messages.parse` for structure; (c) a deterministic
  `safety.py` post-check that asserts exactly one action, the disclaimer is present, and
  no banned diagnostic/causal phrasing (curated lexicon), with violations rejected/retried.
- **Rationale**: Principle II is non-negotiable; relying on the prompt alone is
  insufficient, so a code-level gate enforces FR-014/FR-015 and SC-004.
- **Alternatives considered**: Prompt-only enforcement — rejected (not verifiable). A
  second "LLM-as-judge" pass — deferred to a later phase; a deterministic lexical check is
  cheaper and adequate for the PoC.

## D9. Primary interface

- **Decision**: Streamlit single-page dashboard (P4) as the primary surface; a minimal
  CLI renderer (P1) for the MVP slice; optional FastAPI (P6) for programmatic access.
- **Rationale**: Stakeholder chose Streamlit for fastest path to a visual demo. CLI keeps
  P1 truly minimal and independently testable; the API is additive and reuses the engine.
- **Alternatives considered**: FastAPI + bespoke JS frontend (more production-shaped, more
  work; deferred to the optional slice); CLI-only (insufficient for the intended demo
  audience).

## D10. Testing strategy & LLM stubbing

- **Decision**: Deterministic suite (`unit/`, `contract/`) runs with no API key, using a
  stubbed Anthropic client that returns canned schema-valid insight payloads from
  `tests/fixtures/`. A separate, optionally-skipped live smoke test exercises the real
  model when `ANTHROPIC_API_KEY` is set.
- **Rationale**: Constitution Quality Gates — the deterministic suite must pass without a
  real key; golden tests pin analytics; contract tests validate against `contracts/`.
- **Alternatives considered**: Recording/replay (VCR-style) of real responses — heavier
  than needed; a hand-written stub is simpler and sufficient.

## D11. Numeric library choice

- **Decision**: Standard library (`statistics.mean`, `datetime`) for baselines/trends;
  introduce `numpy`/`pandas` only inside the synthetic generator if it materially
  simplifies bulk generation. Avoid a hard pandas dependency in the core analytics path.
- **Rationale**: Keeps the deterministic core lightweight and its outputs easy to reason
  about for golden tests; avoids float-formatting surprises from dataframe operations.
- **Alternatives considered**: pandas-centric pipeline — convenient but adds a heavy dep
  and dtype/formatting nondeterminism risk for a small daily-record workload.

## D12. Prompt caching

- **Decision**: Mark the (large, stable) system prompt with `cache_control: ephemeral` so
  repeated insight generations in a demo session reuse the cached prefix; keep the
  volatile comparison object in the user turn after the cache breakpoint.
- **Rationale**: Lowers latency/cost across repeated demo runs (supports SC-008) at no
  correctness cost; the system prompt is frozen and deterministic, satisfying the
  prefix-stability requirement.
- **Alternatives considered**: No caching — acceptable but leaves easy latency/cost on the
  table for a multi-run demo.

## Open questions / deferred to later phases

- Per-metric (rather than global ±15%) trend thresholds — Phase 2.
- LLM-as-judge safety/quality scoring — later phase.
- RAG-backed, evidence-cited recommendations — Phase 2 (architecturally reserved).
- Live device/provider OAuth ingestion — Phase 3 (swap the `data/` source behind the same
  canonical schema).
