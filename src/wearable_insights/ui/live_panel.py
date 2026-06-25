"""Live signals panel — a Streamlit fragment that polls the simulated wearable API.

Each ``run_every`` tick models one API *sync*: the simulated device clock advances by
``DEVICE_SAMPLE_MINUTES`` and the newest reading is appended to a rolling buffer kept
in ``st.session_state``. Because a fragment reruns in isolation, these periodic syncs
never re-trigger the LLM pipeline, nudges, or chat.
"""

from __future__ import annotations

import time
from collections import deque
from datetime import date

import streamlit as st

from wearable_insights import live_anomaly, nudges
from wearable_insights.config import (
    BASELINE_HISTORY_DAYS,
    BASELINE_HORIZONS,
    BASELINE_MIN_SAMPLES,
    BASELINE_SAMPLE_STEP_MINUTES,
    BASELINE_SEED,
    DEVICE_SAMPLE_MINUTES,
    LIVE_BUFFER_POINTS,
    LIVE_FETCH_INTERVAL_SECS,
    MAX_NUDGES_PER_DAY,
)
from wearable_insights.data import live
from wearable_insights.data.slotted_baselines import (
    SlottedBaselineSet,
    build_slotted_baselines,
    day_type as _day_type,
)
from wearable_insights.models import AnomalySeverity, Nudge, NudgeSet, _SEVERITY_ORDER
from wearable_insights.ui import charts, components, theme

_START_MINUTE = 8 * 60  # device clock starts at 08:00


def _load_generate_fn(model: str | None):
    """Lazily build a model-bound insight generator; None if unavailable (no key/SDK)."""
    try:
        from wearable_insights.llm.insight import generate_insights  # noqa: PLC0415

        if model is None:
            return generate_insights
        return lambda comparison: generate_insights(comparison, model=model)
    except Exception:  # pragma: no cover — missing SDK / import error
        return None


def _merge_nudges(
    existing: NudgeSet | None,
    fresh: list[Nudge],
    user_id: str,
    analysis_date: date,
) -> NudgeSet:
    """Merge freshly-raised nudges into the session set: newest-per-id, severity-ordered, capped.

    Session-state Nudge instances may be stale after a Streamlit hot-reload (Pydantic v2
    sees a different class object). Serialising to dicts before NudgeSet construction
    forces re-validation and avoids that mismatch.
    """
    by_id: dict[str, dict] = {
        n.nudge_id: n.model_dump()
        for n in (existing.nudges if existing else [])
    }
    for n in fresh:
        by_id[n.nudge_id] = n.model_dump()
    ordered = sorted(
        by_id.values(),
        key=lambda d: _SEVERITY_ORDER[AnomalySeverity(d["severity"])],
        reverse=True,
    )
    return NudgeSet(user_id=user_id, analysis_date=analysis_date, nudges=ordered[:MAX_NUDGES_PER_DAY])


def _auto_generate_nudges(
    profile_dict: dict,
    analysis_date: date,
    slotted: SlottedBaselineSet,
    buffer: list[dict],
    mode: str,
    model: str | None,
    current_minute: int,
    current_day_type: str,
) -> list[Nudge]:
    """Deterministic detection → de-dup/cooldown → reuse the nudge generation + safety path.

    Returns the newly-raised nudges (possibly empty). Never raises into the fragment —
    failures degrade to "no new nudge" so the live auto-refresh keeps running (FR-013).
    """
    anomalies = live_anomaly.detect_live_anomalies(
        buffer,
        slotted,
        mode,
        current_minute=current_minute,
        current_day_type=current_day_type,
    )
    state = st.session_state.setdefault("live_nudge_state", {})
    new_anomalies, _ = live_anomaly.filter_new_anomalies(anomalies, state, time.time())
    if not new_anomalies:
        return []

    fn = _load_generate_fn(model)
    if fn is None:
        return []

    user_id = profile_dict.get("user_id", "unknown")
    try:
        synthesized = live_anomaly.synthesize_comparison(
            new_anomalies,
            buffer,
            slotted,
            user_id,
            analysis_date,
            current_minute=current_minute,
            current_day_type=current_day_type,
        )
        # In wake-up mode the remapped anomalies carry AnomalyTheme.sleep, so the
        # nudge generator routes them to comparison.sleep. Merge in the daily
        # pipeline's sleep section (already computed with proper 7/30-day baselines)
        # so the LLM is grounded in real overnight metrics, not just live HRV.
        if mode == "wake-up":
            daily = st.session_state.get("active_comparison")
            if daily is not None and daily.sleep:
                synthesized = synthesized.model_copy(update={"sleep": daily.sleep})
        fresh_set = nudges.generate_nudge_set(new_anomalies, synthesized, generate_fn=fn)
    except Exception:  # pragma: no cover — generation/model error must not break refresh
        return []

    merged = _merge_nudges(st.session_state.get("nudge_set"), fresh_set.nudges, user_id, analysis_date)
    st.session_state.nudge_set = merged
    fresh_ids = {n.nudge_id for n in fresh_set.nudges}
    return [n for n in merged.nudges if n.nudge_id in fresh_ids]


def _today_record(profile_dict: dict, analysis_date: date) -> dict:
    target = analysis_date.isoformat()
    records = profile_dict.get("records", [])
    return next(
        (r for r in records if r.get("date") == target),
        records[-1] if records else {},
    )


def render_live_panel(
    profile_dict: dict,
    analysis_date: date,
    model: str | None = None,
    has_api_key: bool = True,
) -> None:
    """Render one live-feed sync.

    Not decorated with ``@st.fragment`` directly: ``app.py`` wraps it via
    ``st.fragment(render_live_panel, run_every=...)`` so the sync interval can be
    adjusted at runtime from the sidebar (default ``LIVE_FETCH_INTERVAL_SECS``).
    """
    today_rec = _today_record(profile_dict, analysis_date)
    # Flat baselines used only for rendering signal cards (display) and buffer seeding.
    flat_baselines = live.live_baselines(today_rec)

    components.section_label("Live signals · synced from wearable")
    mode = st.radio(
        "Activity context",
        live.MODES,
        horizontal=True,
        key="live_mode",
        format_func=str.capitalize,
    )

    # Seed the buffer once per profile load (reset elsewhere on profile change).
    if not st.session_state.get("live_buffer"):
        st.session_state.live_buffer = deque(
            live.seed_buffer(
                flat_baselines, mode, _START_MINUTE, LIVE_BUFFER_POINTS, DEVICE_SAMPLE_MINUTES
            ),
            maxlen=LIVE_BUFFER_POINTS,
        )
        st.session_state.live_device_minute = _START_MINUTE
        # Reset auto-nudge de-dup state whenever the buffer is (re)seeded.
        st.session_state.live_nudge_state = {}

    # Build slotted baselines once per profile load (stored alongside the buffer).
    # Building takes ~100ms for 60 days at 5-min cadence — acceptable at session start.
    if st.session_state.get("live_slotted_baselines") is None:
        st.session_state.live_slotted_baselines = build_slotted_baselines(
            today_rec,
            seed=BASELINE_SEED,
            history_days=BASELINE_HISTORY_DAYS,
            horizons=BASELINE_HORIZONS,
            min_samples=BASELINE_MIN_SAMPLES,
            sample_step_minutes=BASELINE_SAMPLE_STEP_MINUTES,
            ref_date=analysis_date,
        )

    # One API "sync": advance the device clock and append the newest reading.
    minute = (st.session_state.live_device_minute + DEVICE_SAMPLE_MINUTES) % 1440
    st.session_state.live_device_minute = minute
    buffer: deque = st.session_state.live_buffer
    buffer.append(live.fetch_latest_sample(flat_baselines, minute, mode))

    samples = list(buffer)
    latest = samples[-1]
    prev = samples[-2] if len(samples) > 1 else latest

    # Determine current slot context for display and detection.
    current_dt = _day_type(analysis_date.weekday())

    cards: list[str] = []
    for sig in live.LIVE_SIGNALS:
        key = sig["key"]
        value = latest[key]
        status = live.signal_status(key, value)
        delta = value - prev[key]
        arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
        trend = f"{arrow} {'normal' if status == 'ok' else 'watch'}"
        display = f"{value:.1f}" if sig["dec"] else f"{value}"
        cards.append(
            components.signal_card_html(sig["label"], display, sig["unit"], status, trend)
        )
    components.render_signal_grid(cards)

    r1c1, r1c2, r1c3 = st.columns(3)
    for col, field, title, color in (
        (r1c1, "hr",        "Heart rate (bpm)", theme.CRIT),
        (r1c2, "hrv",       "HRV (ms)",         theme.ACCENT),
        (r1c3, "spo2",      "SpO₂ (%)",         theme.OK),
    ):
        ch = charts.live_line(samples, field, title, color)
        if ch is not None:
            col.altair_chart(ch, use_container_width=True)

    r2c1, r2c2 = st.columns(2)
    for col, field, title, color in (
        (r2c1, "skin_temp", "Skin temp (°C)",   theme.WARN),
        (r2c2, "resp_rate", "Respiration (rpm)", theme.COBALT),
    ):
        ch = charts.live_line(samples, field, title, color)
        if ch is not None:
            col.altair_chart(ch, use_container_width=True)

    interval = st.session_state.get("live_fetch_interval", LIVE_FETCH_INTERVAL_SECS)
    st.caption(
        f"⌚ Last synced {latest['clock']} (device time) · context: {mode} · "
        f"auto-syncs every {interval:g}s "
        f"({DEVICE_SAMPLE_MINUTES} min device samples)"
    )

    # ── Automatic anomaly nudges (Feature 003/004) ───────────────────────────
    # Slotted detection over the live window → reuse the nudge generation + safety path.
    # Runs inside the fragment so new nudges surface without a full page rerun.
    if not has_api_key:
        st.caption("🔔 Auto-nudges need an AI model credential — set one to enable them.")
        return

    slotted: SlottedBaselineSet = st.session_state.live_slotted_baselines
    new_nudges = _auto_generate_nudges(
        profile_dict,
        analysis_date,
        slotted,
        samples,
        mode,
        model,
        current_minute=minute,
        current_day_type=current_dt,
    )
    for nudge in new_nudges:
        st.toast(f"🔔 {nudge.insight.title}", icon="🔔")
    if new_nudges:
        st.markdown("**🔔 New auto-nudge**" + ("s" if len(new_nudges) > 1 else ""))
        for nudge in new_nudges:
            with st.container(border=True):
                st.markdown(f"**{nudge.insight.title}**")
                st.caption(nudge.insight.summary)
                st.markdown(f"**Suggested action:** {nudge.insight.action}")
        st.caption("💬 Open it from **Today's Nudges** to chat about it.")
