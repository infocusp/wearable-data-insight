# wearable-data-insight

Deterministic wearable analytics (sleep/recovery/activity baselines → comparison →
anomaly → nudge) plus a bounded LLM narrative layer, under a non-diagnostic safety gate.

## Run

Dashboard (Streamlit, the primary demo surface):

```bash
PYTHONPATH=src streamlit run src/wearable_insights/app.py
```

FastAPI sidecar (wraps the same engine for external callers — currently
[ClaimGuard](https://github.com/prathmeshinfocusp/claim-guard)):

```bash
PYTHONPATH=src uvicorn wearable_insights.api:app --reload --port 8000
```

See [`CLAUDE.md`](CLAUDE.md) for architecture, active technologies, and the constitution's
non-negotiable rules. The ClaimGuard integration — endpoint list, the stateless design,
and every deviation from the frozen `001` API contract — is documented in
[`specs/005-claimguard-integration/research.md`](specs/005-claimguard-integration/research.md).
`Dockerfile.api` builds the sidecar image; the existing `Dockerfile` (Hugging Face Spaces
target) is unchanged.
