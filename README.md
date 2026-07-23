# wearable-data-insight

Wearable Insights Translation Engine — a Streamlit dashboard that turns wearable
daily summaries into empathetic, deterministic-analysis-backed insights and nudges.

## Run locally

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # add your API key(s)
streamlit run src/wearable_insights/app.py
```

The dashboard works without any key (deterministic analysis only); set
`ANTHROPIC_API_KEY` and/or `GEMINI_API_KEY` in `.streamlit/secrets.toml` (or a
root `.env` file) to unlock nudges and chat.

## Deploy to Streamlit Community Cloud

1. Push this repo to GitHub.
2. On [streamlit.io/cloud](https://streamlit.io/cloud), click **New app** and pick
   the repo/branch.
3. Set **Main file path** to `src/wearable_insights/app.py`. Python version is
   picked up from `.python-version` (3.12).
4. Under **Settings → Secrets**, paste the contents of
   `.streamlit/secrets.toml.example` filled in with real values (Anthropic and/or
   Gemini key). Nothing else is required — `requirements.txt` covers all deps.
5. Deploy. Note the app's chat history (SQLite under `data/`) and the live-buffer
   session state live on the container's local disk, so they reset whenever the
   app restarts or reboots on inactivity — expected for this demo, not a bug.

The optional 3 GB PMData set (`pmdata/`) is local-only and never required — the
"Real World (PMData)" data-source toggle simply stays hidden when that folder
isn't present, as it won't be on a fresh Cloud deploy.
