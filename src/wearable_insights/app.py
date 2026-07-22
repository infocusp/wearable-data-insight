"""Streamlit dashboard — Wearable Insights Translation Engine (Phase 2)."""

from __future__ import annotations

import sys
from pathlib import Path

# Make package importable when run via `streamlit run src/wearable_insights/app.py`
_src_root = Path(__file__).resolve().parent.parent
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

from datetime import date

import streamlit as st

from wearable_insights import memory, store
from wearable_insights.config import (
    DEVICE_SAMPLE_MINUTES,
    DISCLAIMER,
    LIVE_FETCH_INTERVAL_SECS,
    MODEL_OPTIONS,
    WEARABLE_MODEL,
    get_api_key_for_model,
)
from wearable_insights.data.pmdata import (
    PMDATA_SUBJECTS,
    load_pmdata_subject,
    pmdata_root_from_env,
)
from wearable_insights.data.synthetic import (
    DEFAULT_ANALYSIS_DATE,
    DEFAULT_HISTORY_DAYS,
    PROFILE_NAMES,
    generate_synthetic_profile,
    generate_today_record,
)
from wearable_insights.llm.chat import chat_reply
from wearable_insights.models import (
    ComparisonObject,
    MetricComparison,
    Nudge,
    NudgeSet,
)
from wearable_insights.pipeline import build_comparison, run_nudge_pipeline
from wearable_insights.ui import charts, components
from wearable_insights.ui.live_panel import render_live_panel
from wearable_insights.ui.theme import inject_theme


# ─── Display metadata ─────────────────────────────────────────────────────────

_ALL_PROFILES = ("recovery_deficit",) + tuple(PROFILE_NAMES)

_PROFILE_LABELS: dict[str, str] = {
    "recovery_deficit": "Recovery Deficit  (MVP demo)",
    "healthy_consistent": "Healthy & Consistent",
    "poor_sleep_week": "Poor Sleep Week",
    "low_activity": "Low Activity",
    "recovery_decline": "Recovery Decline",
}

# comparison_key → (display_name, unit)
_METRIC_META: dict[str, tuple[str, str]] = {
    "sleep_duration": ("Sleep Duration", "min"),
    "sleep_score":    ("Sleep Score", "/ 100"),
    "deep_sleep":     ("Deep Sleep", "min"),
    "rem_sleep":      ("REM Sleep", "min"),
    "resting_hr":     ("Resting HR", "bpm"),
    "hrv":            ("HRV (RMSSD)", "ms"),
    "stress":         ("Stress Score", "/ 100"),
    "steps":          ("Steps", "steps"),
    "active_minutes": ("Active Minutes", "min"),
}

# record field → comparison key (for today's snapshot)
_RECORD_TO_COMPARISON: dict[str, str] = {
    "sleep_duration_minutes": "sleep_duration",
    "sleep_score":            "sleep_score",
    "deep_sleep_minutes":     "deep_sleep",
    "rem_sleep_minutes":      "rem_sleep",
    "hrv_rmssd_ms":           "hrv",
    "resting_hr":             "resting_hr",
    "stress_score":           "stress",
    "steps":                  "steps",
    "active_minutes":         "active_minutes",
}

# Maps a 30-day evaluation tag to a signal-card status (dot/trend color).
_TAG_STATUS: dict[str, str] = {
    "Stable / Within Normal Baseline": "ok",
    "Significantly Elevated":          "warn",
    "Significantly Depressed":         "warn",
    "Critically Elevated":             "crit",
    "Critically Depressed":            "crit",
}

_TREND_ARROW: dict[str, str] = {"up": "↑", "down": "↓", "stable": "→"}

_SECTION_ICONS: dict[str, str] = {
    "Sleep":                     "🌙",
    "Heart Health & Recovery":   "❤️",
    "Activity":                  "🏃",
}

_WINDOW_COLUMNS: list[tuple[str, str]] = [
    ("weekly",     "7-day Δ"),
    ("monthly",    "30-day Δ"),
    ("weekday",    "Weekday Δ"),
    ("sixty_day",  "60-day Δ"),
    ("ninety_day", "90-day Δ"),
]

_WINDOW_DEFAULTS: dict[str, bool] = {
    "weekly":     True,
    "monthly":    True,
    "weekday":    True,
    "sixty_day":  False,
    "ninety_day": False,
}


@st.cache_data(show_spinner=False)
def _load_pmdata_cached(subject_id: str, pmdata_root: str) -> dict:
    return load_pmdata_subject(subject_id, pmdata_root)


def _get_window(mc: MetricComparison, key: str):  # type: ignore[return]
    return getattr(mc, key)


# ─── Formatting helpers ────────────────────────────────────────────────────────

def _fmt(key: str, value: float | None) -> str:
    if value is None:
        return "—"
    if key == "sleep_duration":
        h, m = int(value) // 60, int(value) % 60
        return f"{h}h {m}m"
    if key == "steps":
        return f"{int(value):,}"
    if key == "hrv":
        return f"{value:.1f}"
    return str(int(round(value)))


# ─── Component renderers ───────────────────────────────────────────────────────

def _metric_by_key(comparison: ComparisonObject, key: str) -> MetricComparison | None:
    for section in (comparison.sleep, comparison.heart_health, comparison.activity):
        if key in section:
            return section[key]
    return None


def _render_todays_snapshot(profile_dict: dict, comparison: ComparisonObject) -> None:
    components.section_label("Today's snapshot")

    records = profile_dict.get("records", [])
    target = comparison.analysis_date.isoformat()
    record: dict = next((r for r in records if r.get("date") == target), records[-1] if records else {})

    snapshot_items = [
        ("sleep_duration_minutes", "Sleep Duration"),
        ("sleep_score",            "Sleep Score"),
        ("deep_sleep_minutes",     "Deep Sleep"),
        ("rem_sleep_minutes",      "REM Sleep"),
        ("hrv_rmssd_ms",           "HRV (RMSSD)"),
        ("resting_hr",             "Resting HR"),
        ("stress_score",           "Stress Score"),
        ("steps",                  "Steps"),
        ("active_minutes",         "Active Minutes"),
    ]

    cards: list[str] = []
    for field, label in snapshot_items:
        key = _RECORD_TO_COMPARISON.get(field, field)
        _, unit = _METRIC_META.get(key, ("", ""))
        raw = record.get(field)
        formatted = _fmt(key, raw)
        if formatted == "—":
            cards.append(components.signal_card_html(label, "—"))
            continue

        # sleep_duration is already rendered as "7h 30m" — no extra unit needed.
        card_unit = "" if key == "sleep_duration" else unit
        status, trend = "neutral", ""
        mc = _metric_by_key(comparison, key)
        if mc is not None:
            status = _TAG_STATUS.get(mc.monthly.evaluation_tag, "neutral")
            pct = mc.monthly.percentage_change
            if pct is not None:
                arrow = _TREND_ARROW.get(mc.monthly.trend, "→")
                trend = f"{arrow} {pct:+.0f}% vs 30d"
        cards.append(components.signal_card_html(label, formatted, card_unit, status, trend))

    components.render_signal_grid(cards)


def _render_comparison_section(
    title: str,
    metrics: dict[str, MetricComparison],
    active_windows: list[str],
    *,
    expanded: bool = True,
) -> None:
    if not metrics:
        return

    icon = _SECTION_ICONS.get(title, "📊")
    widths = [2.2, 1.1] + [1.2] * len(active_windows) + [2.8]

    with st.expander(f"{icon} {title}", expanded=expanded):
        h = st.columns(widths)
        headers = (
            ["**Metric**", "**Today**"]
            + [f"**{hdr}**" for key, hdr in _WINDOW_COLUMNS if key in active_windows]
            + ["**Status**"]
        )
        for col, text in zip(h, headers):
            col.markdown(text)
        st.divider()

        for key, mc in metrics.items():
            name, unit = _METRIC_META.get(key, (key, ""))
            c = st.columns(widths)

            c[0].markdown(
                f"**{name}**" + (f" <small>({unit})</small>" if unit else ""),
                unsafe_allow_html=True,
            )
            c[1].write(_fmt(key, mc.current_value))

            for i, (win_key, _) in enumerate(
                (wc for wc in _WINDOW_COLUMNS if wc[0] in active_windows),
                start=2,
            ):
                wc = _get_window(mc, win_key)
                c[i].markdown(
                    components.fmt_delta(wc.percentage_change, wc.trend),
                    unsafe_allow_html=True,
                )

            c[-1].markdown(
                components.tag_badge(mc.monthly.evaluation_tag), unsafe_allow_html=True
            )

            if mc.flags:
                st.caption("⚠️ " + "  ·  ".join(mc.flags))


def _render_associations(comparison: ComparisonObject) -> None:
    if not comparison.candidate_associations:
        return

    with st.expander("🔗 Candidate Associations", expanded=False):
        st.caption(
            "Observational co-occurrence patterns detected from your data. "
            "These are associations — not diagnoses, not causal claims."
        )
        for assoc in comparison.candidate_associations:
            st.markdown(f"**{assoc.relation}**")
            st.write(assoc.description)
            st.caption("Signals: " + "  ·  ".join(assoc.signals))
            st.divider()


def _render_data_quality(comparison: ComparisonObject) -> None:
    dq = comparison.data_quality
    issues: list[str] = []
    if dq.missing_fields:
        issues.append(f"Missing fields: {', '.join(dq.missing_fields)}")
    if dq.invalid_fields:
        issues.append(f"Invalid fields: {', '.join(dq.invalid_fields)}")
    if dq.low_confidence:
        issues.append("Low confidence baselines (< 7 days of history)")
    if issues:
        st.warning("**Data quality notes:** " + "  ·  ".join(issues), icon="⚠️")


def _render_history(profile_dict: dict) -> None:
    """Demo-style history/trend charts built from the daily records (static)."""
    records = profile_dict.get("records", [])
    if not records:
        return

    components.section_label("Sleep · last 7 nights")
    sleep_chart = charts.sleep_stage_chart(records)
    if sleep_chart is not None:
        st.altair_chart(sleep_chart, use_container_width=True)

    components.section_label("Activity · last 7 days")
    act_chart = charts.activity_chart(records)
    if act_chart is not None:
        st.altair_chart(act_chart, use_container_width=True)

    components.section_label("Trends · last 30 days")
    cols = st.columns(3)
    for col, metric in zip(cols, ("hrv", "resting_hr", "sleep_duration")):
        chart = charts.trend_line(records, metric)
        if chart is not None:
            col.altair_chart(chart, use_container_width=True)


# ─── Nudge feed & chat ─────────────────────────────────────────────────────────

def _nudge_first_message(nudge: Nudge) -> str:
    """Synthetic opening message shown as the chatbot's first turn (no LLM call)."""
    return (
        f"**{nudge.insight.title}**\n\n"
        f"{nudge.insight.summary}\n\n"
        f"**Suggested action:** {nudge.insight.action}\n\n"
        "_I'm here to help you understand this nudge. What would you like to know?_"
    )


def _switch_session(new_id: str | None, model: str) -> None:
    """Select a different chat, distilling memory from the one we're leaving."""
    prev = st.session_state.active_session_id
    if prev and prev != new_id:
        try:
            memory.finalize_session(prev, st.session_state.user_key, model=model)
        except Exception:  # pragma: no cover - memory is best-effort
            pass
    st.session_state.active_session_id = new_id


def _open_nudge_chat(user_key: str, nudge: Nudge, analysis_date: date) -> str:
    """Return the session id for this nudge, creating + seeding it on first open."""
    existing = store.find_session_by_nudge(user_key, nudge.nudge_id)
    if existing:
        return existing["id"]
    session_id = store.create_session(
        user_key,
        title=nudge.insight.title,
        kind="nudge",
        nudge_id=nudge.nudge_id,
        analysis_date=analysis_date.isoformat(),
    )
    # Seed the synthetic opener as the first (assistant) turn.
    store.add_turn(session_id, "assistant", _nudge_first_message(nudge))
    return session_id


_SEV_ICON: dict[str, str] = {"critical": "🔴", "significant": "🟠", "moderate": "🟡"}


def _render_nudge_history(
    nudge_set: NudgeSet | None, user_key: str, analysis_date: date, model: str
) -> None:
    """Nudges rendered as compact clickable items in the history pane."""
    st.markdown("**🔔 Today's Nudges**")
    if nudge_set is None:
        st.caption("Nudges appear here automatically as the live feed detects anomalies.")
        return
    if not nudge_set.nudges:
        st.caption("No nudges today. ✅")
        return

    active_id = st.session_state.active_session_id
    for nudge in nudge_set.nudges:
        icon = _SEV_ICON.get(nudge.severity.value, "🔔")
        title = nudge.insight.title
        if len(title) > 28:
            title = title[:27] + "…"
        existing = store.find_session_by_nudge(user_key, nudge.nudge_id)
        is_active = bool(existing and existing["id"] == active_id)
        if st.button(
            f"{icon} {title}",
            key=f"hist_nudge_{nudge.nudge_id}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
        ):
            session_id = _open_nudge_chat(user_key, nudge, analysis_date)
            _switch_session(session_id, model)
            st.rerun()


def _session_label(s: dict) -> str:
    icon = "🔔" if s["kind"] == "nudge" else "💬"
    title = s["title"] or "Untitled chat"
    if len(title) > 34:
        title = title[:33] + "…"
    return f"{icon} {title}"


def _render_session_list(user_key: str, model: str) -> None:
    """Session list: new-chat button + browsable, resumable chat history."""
    if st.button("➕ New chat", use_container_width=True, key="new_chat_btn"):
        new_id = store.create_session(
            user_key, title="New chat", kind="free",
            analysis_date=st.session_state.get("active_analysis_date"),
        )
        _switch_session(new_id, model)
        st.rerun()

    sessions = store.list_sessions(user_key)
    if not sessions:
        st.caption("No conversations yet. Start one, or chat about a nudge.")
        return

    active_id = st.session_state.active_session_id
    for s in sessions:
        is_active = s["id"] == active_id
        if st.button(
            _session_label(s),
            key=f"sess_{s['id']}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
        ):
            _switch_session(s["id"], model)
            st.rerun()


def _render_nudge_history_pane(user_key: str, analysis_date: date, model: str) -> None:
    """Polls session state so new auto-nudges appear without a full rerun.

    Wrapped as a fragment at call time via ``st.fragment(..., run_every=...)`` so it
    shares the sidebar-adjustable live sync interval.
    """
    _render_nudge_history(st.session_state.nudge_set, user_key, analysis_date, model)
    st.divider()
    st.markdown("**💬 Chats**")
    _render_session_list(user_key, model)


def _render_memory_panel(user_key: str, profile_dict: dict, analysis_date: date) -> None:
    facts = [m["content"] for m in store.get_memory(user_key, "fact")]
    patterns = memory.compute_recurring_patterns(profile_dict, analysis_date)
    summaries = [m["content"] for m in store.get_memory(user_key, "summary")]
    if not (facts or patterns or summaries):
        return
    with st.expander("🧠 What the assistant remembers about you", expanded=False):
        if facts:
            st.markdown("**Stated facts & preferences**")
            for f in facts:
                st.markdown(f"- {f}")
        if patterns:
            st.markdown("**Recurring patterns in recent data**")
            for p in patterns:
                st.markdown(f"- {p}")
        if summaries:
            st.markdown("**Recent conversations**")
            for s in summaries[:5]:
                st.markdown(f"- {s}")


def _render_conversation(
    user_key: str,
    comparison: ComparisonObject,
    nudge_set: NudgeSet | None,
    profile_dict: dict,
    analysis_date: date,
    selected_model: str,
) -> None:
    """Right pane: the active conversation, persisted to the store."""
    active_id = st.session_state.active_session_id
    session = store.get_session(active_id) if active_id else None
    if session is None or session["user_id"] != user_key:
        st.session_state.active_session_id = None
        st.info(
            "Select a chat from the left sidebar, hit **➕ New chat**, "
            "or click **💬 Chat about this** on a nudge.",
            icon="💬",
        )
        return

    # Resolve nudge grounding when this session is anchored to a currently-loaded nudge.
    nudge_obj: Nudge | None = None
    if session["nudge_id"] and nudge_set is not None:
        nudge_obj = next(
            (n for n in nudge_set.nudges if n.nudge_id == session["nudge_id"]), None
        )

    header_cols = st.columns([6, 1])
    header_cols[0].markdown(f"### {session['title']}")
    if header_cols[1].button("🗑", key="del_session", help="Delete this conversation"):
        store.delete_session(active_id)
        st.session_state.active_session_id = None
        st.rerun()

    if session["nudge_id"] and nudge_obj is None:
        st.caption(
            "Resumed nudge chat — grounding falls back to today's overall data "
            "since that nudge isn't loaded right now."
        )

    history = store.get_turns(active_id)
    for msg in history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if user_input := st.chat_input("Ask anything about today's data…"):
        store.add_turn(active_id, "user", user_input)
        # Auto-title a fresh free chat from its first user message.
        if session["kind"] == "free" and session["title"] == "New chat":
            store.rename_session(active_id, user_input[:40])
        with st.chat_message("user"):
            st.markdown(user_input)

        history = history + [{"role": "user", "content": user_input}]
        mem_block = memory.build_memory_block(user_key, profile_dict, analysis_date)
        with st.spinner("Thinking…"):
            try:
                reply = chat_reply(
                    history,
                    comparison,
                    nudge=nudge_obj,
                    nudge_set=nudge_set,
                    memory_block=mem_block,
                    model=selected_model,
                    profile_dict=profile_dict,
                )
            except (RuntimeError, ValueError) as exc:
                reply = f"_Sorry, I couldn't get a reply: {exc}_"

        store.add_turn(active_id, "assistant", reply)
        with st.chat_message("assistant"):
            st.markdown(reply)


# ─── Main app ──────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="Infocusp · Wearable Health AI",
        page_icon="🩺",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    inject_theme()

    # ── Session state bootstrap ────────────────────────────────────────────────
    _SS_DEFAULTS: dict = {
        "data_source": "synthetic",
        "active_comparison": None,
        # synthetic
        "data_seed": 42,
        "today_seed": 42,
        "last_profile_key": None,
        "base_profile_dict": None,
        "active_profile_dict": None,
        # pmdata
        "pmdata_subject": "p02",
        "pmdata_analysis_date": None,
        "pmdata_profile_dict": None,
        # Phase 2: nudges  ·  Phase 3: persistent chat + memory
        "nudge_set": None,
        "active_session_id": None,
        "user_key": None,
        "active_analysis_date": None,
        # Live signals feed + auto-nudge de-dup state (reset on profile/source change)
        "live_buffer": None,
        "live_device_minute": None,
        "live_nudge_state": {},
        "live_slotted_baselines": None,
        # Sidebar-adjustable wall-clock seconds between live "syncs".
        "live_fetch_interval": LIVE_FETCH_INTERVAL_SECS,
    }
    for k, v in _SS_DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v

    store.init_db()

    _pmdata_root = str(pmdata_root_from_env(
        str(Path(__file__).resolve().parent.parent.parent / "pmdata")
    ))
    # The PMData set is a 3 GB local-only download; on hosted deploys (no pmdata/
    # folder present) the toggle is hidden rather than left to error on selection.
    _pmdata_available = Path(_pmdata_root).is_dir() and any(Path(_pmdata_root).iterdir())
    if not _pmdata_available:
        st.session_state.data_source = "synthetic"

    # ── Sidebar ────────────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("Settings")

        if _pmdata_available:
            data_source = st.radio(
                "Data source",
                options=["synthetic", "pmdata"],
                format_func=lambda s: "Synthetic (demo)" if s == "synthetic" else "Real World (PMData)",
                horizontal=True,
                index=0 if st.session_state.data_source == "synthetic" else 1,
            )
            if data_source != st.session_state.data_source:
                st.session_state.data_source = data_source
                st.session_state.active_comparison = None
                st.session_state.nudge_set = None
                st.session_state.active_session_id = None
                st.session_state.live_buffer = None
                st.session_state.live_slotted_baselines = None
        else:
            data_source = "synthetic"

        st.divider()

        if data_source == "synthetic":
            profile_key = st.selectbox(
                "User profile",
                options=_ALL_PROFILES,
                format_func=lambda k: _PROFILE_LABELS.get(k, k),
                index=0,
            )
            if st.session_state.last_profile_key != profile_key:
                st.session_state.last_profile_key = profile_key
                st.session_state.data_seed = 42
                st.session_state.today_seed = 42
                st.session_state.base_profile_dict = None
                st.session_state.active_profile_dict = None
                st.session_state.active_comparison = None
                st.session_state.nudge_set = None
                st.session_state.active_session_id = None
                st.session_state.live_buffer = None
            st.session_state.live_slotted_baselines = None
        else:
            pmdata_subject = st.selectbox(
                "Subject",
                options=PMDATA_SUBJECTS,
                index=PMDATA_SUBJECTS.index(st.session_state.pmdata_subject),
            )
            if pmdata_subject != st.session_state.pmdata_subject:
                st.session_state.pmdata_subject = pmdata_subject
                st.session_state.pmdata_profile_dict = None
                st.session_state.pmdata_analysis_date = None
                st.session_state.active_comparison = None
                st.session_state.nudge_set = None
                st.session_state.active_session_id = None
                st.session_state.live_buffer = None
            st.session_state.live_slotted_baselines = None

        st.divider()

        st.subheader("Live feed")
        st.caption(
            "How often the simulated wearable syncs a new sample. Each sync advances the "
            f"device clock by {DEVICE_SAMPLE_MINUTES} min."
        )
        st.session_state.live_fetch_interval = st.number_input(
            "Sync interval (seconds)",
            min_value=1.0,
            max_value=60.0,
            value=float(st.session_state.live_fetch_interval),
            step=1.0,
            help="Lower = faster live updates. Default is 5s.",
        )

        st.divider()

        st.subheader("Trend windows")
        st.caption("Select which comparison windows to show in the analysis table.")
        active_windows: list[str] = []
        for win_key, win_label in _WINDOW_COLUMNS:
            if st.checkbox(win_label, value=_WINDOW_DEFAULTS[win_key], key=f"win_{win_key}"):
                active_windows.append(win_key)

        st.divider()

        if data_source == "synthetic":
            regen_today_btn = st.button(
                "🔄 Regenerate today's data",
                help="Re-roll only today's noise while keeping historical records unchanged.",
                use_container_width=True,
            )
            regen_all_btn = st.button(
                "♻️ Regenerate all data",
                help="Regenerate the entire history and today from a new random seed.",
                use_container_width=True,
            )
            st.divider()
        else:
            regen_today_btn = False
            regen_all_btn = False

        _model_ids = list(MODEL_OPTIONS)
        _default_idx = _model_ids.index(WEARABLE_MODEL) if WEARABLE_MODEL in _model_ids else 0
        selected_model = st.selectbox(
            "AI model",
            options=_model_ids,
            format_func=lambda m: MODEL_OPTIONS[m]["display_name"],
            index=_default_idx,
            help="Choose the LLM provider and model used to generate nudges and chat replies.",
        )

        _model_info = MODEL_OPTIONS[selected_model]
        _api_key_env = _model_info["api_key_env"]
        has_api_key = bool(get_api_key_for_model(selected_model))

        if not has_api_key:
            st.warning(
                f"No `{_api_key_env}` found.  \n"
                "Deterministic analysis is available — set the key to unlock nudges.",
                icon="🔑",
            )

        st.caption(
            "🔔 Nudges now fire **automatically** from the live signal feed — "
            "no button needed."
        )
        with st.expander("🛠️ Debug · manual nudge"):
            st.caption(
                "Runs the daily-summary nudge pipeline once (the old manual path). "
                "Kept for demos; the live feed raises nudges on its own."
            )
            simulate_nudge = st.button(
                "🔔 Simulate Nudge (debug)",
                disabled=not has_api_key,
                use_container_width=True,
            )

        if not has_api_key:
            st.caption(f"Export `{_api_key_env}` before starting Streamlit.")

        st.divider()
        if data_source == "synthetic":
            st.caption("Phase 3 · Synthetic data · Anomaly nudges + persistent chat")
        else:
            st.caption("Phase 3 · PMData (real Fitbit exports) · persistent chat")

    # ── Handle regeneration buttons (synthetic only) ───────────────────────────
    if regen_all_btn:
        st.session_state.data_seed += 997
        st.session_state.today_seed = st.session_state.data_seed
        st.session_state.base_profile_dict = None
        st.session_state.active_profile_dict = None
        st.session_state.active_comparison = None
        st.session_state.nudge_set = None
        st.session_state.active_session_id = None
        st.session_state.live_buffer = None
        st.session_state.live_slotted_baselines = None

    if regen_today_btn:
        st.session_state.today_seed += 1
        st.session_state.active_profile_dict = None
        st.session_state.active_comparison = None
        st.session_state.nudge_set = None
        st.session_state.active_session_id = None
        st.session_state.live_buffer = None
        st.session_state.live_slotted_baselines = None

    # ── Load / build profile dict ──────────────────────────────────────────────
    if data_source == "synthetic":
        if st.session_state.base_profile_dict is None:
            with st.spinner("Generating synthetic data and running analysis…"):
                st.session_state.base_profile_dict = generate_synthetic_profile(
                    profile_key,
                    days=DEFAULT_HISTORY_DAYS,
                    end_date=DEFAULT_ANALYSIS_DATE,
                    seed=st.session_state.data_seed,
                )

        if st.session_state.active_profile_dict is None:
            base = st.session_state.base_profile_dict
            today_rec = generate_today_record(
                profile_key,
                seed=st.session_state.today_seed,
                analysis_date=DEFAULT_ANALYSIS_DATE,
                total_days=DEFAULT_HISTORY_DAYS,
            )
            historical = base["records"][:-1]
            st.session_state.active_profile_dict = {**base, "records": historical + [today_rec]}

        profile_dict: dict = st.session_state.active_profile_dict
        analysis_date = DEFAULT_ANALYSIS_DATE

    else:  # pmdata
        if st.session_state.pmdata_profile_dict is None:
            with st.spinner(f"Loading Fitbit data for {st.session_state.pmdata_subject}…"):
                st.session_state.pmdata_profile_dict = _load_pmdata_cached(
                    st.session_state.pmdata_subject, _pmdata_root
                )

        profile_dict = st.session_state.pmdata_profile_dict
        _all_dates = [r["date"] for r in profile_dict["records"]]

        selected_date_str = st.select_slider(
            "Analysis date",
            options=_all_dates,
            value=st.session_state.pmdata_analysis_date or _all_dates[-1],
            key="pmdata_date_slider",
        )
        if selected_date_str != st.session_state.pmdata_analysis_date:
            st.session_state.pmdata_analysis_date = selected_date_str
            st.session_state.active_comparison = None
            st.session_state.nudge_set = None
            st.session_state.active_session_id = None
            st.session_state.live_buffer = None
            st.session_state.live_slotted_baselines = None

        analysis_date = date.fromisoformat(selected_date_str)

    # ── Build comparison (cached until data or date changes) ───────────────────
    if st.session_state.active_comparison is None:
        st.session_state.active_comparison = build_comparison(profile_dict, analysis_date)

    comparison: ComparisonObject = st.session_state.active_comparison

    # ── Per-user key for persisted chats + memory ──────────────────────────────
    user_key = f"{data_source}:{profile_dict.get('user_id', 'unknown')}"
    st.session_state.user_key = user_key
    st.session_state.active_analysis_date = analysis_date.isoformat()

    # ── Simulate Nudge (triggered by button) ──────────────────────────────────
    if simulate_nudge:
        _display_name = MODEL_OPTIONS[selected_model]["display_name"]
        with st.spinner(f"Detecting anomalies and generating nudges via {_display_name}…"):
            result = run_nudge_pipeline(profile_dict, analysis_date, model=selected_model)

        if result.nudge_set is not None:
            st.session_state.nudge_set = result.nudge_set
            n = len(result.nudge_set.nudges)
            if n:
                st.success(f"Found {n} nudge{'s' if n > 1 else ''} for today.", icon="🔔")
            else:
                st.success("All metrics look steady today — no nudges needed.", icon="✅")
        else:
            st.error(f"Nudge simulation failed: {result.error}", icon="❌")

    nudge_set: NudgeSet | None = st.session_state.nudge_set

    # ── Branded header (logo + Live badge + profile chip) ──────────────────────
    components.render_header(profile_dict)

    # ── Two-column main layout: dashboard (left) + chat panel (right) ────────
    dash_col, chat_col = st.columns([2.2, 1.5], gap="large")

    with dash_col:
        components.render_profile_card(profile_dict, comparison.analysis_date)
        _render_data_quality(comparison)

        st.markdown("---")
        # Wrap as a fragment here so the sync interval reflects the sidebar setting.
        _live_interval = st.session_state.live_fetch_interval
        st.fragment(render_live_panel, run_every=_live_interval)(
            profile_dict, analysis_date, selected_model, has_api_key
        )

        st.markdown("---")
        _render_todays_snapshot(profile_dict, comparison)

        st.markdown("---")
        st.markdown("### Comparison Analysis")
        st.caption(
            "Each metric compared against your personal baseline for the selected windows.  "
            "Status always reflects the 30-day baseline.  "
            "Thresholds: ±15% = stable, ±50% = critical."
        )

        _render_comparison_section("Sleep", comparison.sleep, active_windows)
        _render_comparison_section(
            "Heart Health & Recovery", comparison.heart_health, active_windows
        )
        _render_comparison_section("Activity", comparison.activity, active_windows)

        _render_associations(comparison)

        st.markdown("---")
        _render_history(profile_dict)

        st.markdown("---")
        st.caption(f"⚕️ {DISCLAIMER}")

    # ── Right panel: conversation (left) + session history (right) ────────────
    with chat_col:
        conv_pane, history_pane = st.columns([2, 1], gap="medium")

        with conv_pane:
            _render_memory_panel(user_key, profile_dict, analysis_date)
            _render_conversation(
                user_key, comparison, nudge_set, profile_dict, analysis_date, selected_model
            )
            st.markdown("---")
            st.caption(f"⚕️ {DISCLAIMER}")

        with history_pane:
            st.fragment(_render_nudge_history_pane, run_every=st.session_state.live_fetch_interval)(
                user_key, analysis_date, selected_model
            )

    # ── Infocusp footer ────────────────────────────────────────────────────────
    components.render_footer()


main()
