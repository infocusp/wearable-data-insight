"""Altair chart builders (Altair ships with Streamlit — no extra dependency).

All charts are themed for the dark Infocusp palette and driven by plain record
dicts / sample lists. Builders return ``None`` when there isn't enough data so the
caller can skip rendering.
"""

from __future__ import annotations

from typing import Any

import altair as alt
import pandas as pd

from wearable_insights.ui import theme

_AXIS = {"labelColor": theme.TEXT2, "titleColor": theme.TEXT2, "gridColor": theme.BORDER,
         "domainColor": theme.BORDER, "tickColor": theme.BORDER}


def _base(chart: alt.Chart, height: int) -> alt.Chart:
    return (
        chart.properties(height=height, background="transparent")
        .configure_axis(**_AXIS)
        .configure_view(strokeOpacity=0)
        .configure_legend(labelColor=theme.TEXT2, titleColor=theme.TEXT2)
    )


def _recent(records: list[dict], n: int) -> list[dict]:
    return [r for r in records][-n:]


# ── History (static, from daily records) ─────────────────────────────────────────

def sleep_stage_chart(records: list[dict], n: int = 7) -> alt.Chart | None:
    """Stacked deep/REM/light hours for the last *n* nights, with a 7h goal rule."""
    rows: list[dict] = []
    for r in _recent(records, n):
        dur = r.get("sleep_duration_minutes")
        if dur is None:
            continue
        deep = r.get("deep_sleep_minutes") or 0
        rem = r.get("rem_sleep_minutes") or 0
        light = max(dur - deep - rem, 0)
        for stage, val in (("Deep", deep), ("REM", rem), ("Light", light)):
            rows.append({"date": r["date"][5:], "stage": stage, "hours": val / 60.0})
    if not rows:
        return None

    df = pd.DataFrame(rows)
    order = list(dict.fromkeys(df["date"]))
    bars = alt.Chart(df).mark_bar().encode(
        x=alt.X("date:N", sort=order, title=None),
        y=alt.Y("hours:Q", title="Hours", stack="zero"),
        color=alt.Color(
            "stage:N",
            scale=alt.Scale(
                domain=["Deep", "REM", "Light"],
                range=[theme.SLEEP_DEEP, theme.SLEEP_REM, theme.SLEEP_LIGHT],
            ),
            legend=alt.Legend(title="Stage", orient="bottom"),
        ),
        order=alt.Order("stage:N"),
        tooltip=["date:N", "stage:N", alt.Tooltip("hours:Q", format=".1f")],
    )
    goal = alt.Chart(pd.DataFrame({"y": [7.0]})).mark_rule(
        color=theme.SLEEP_DEEP, strokeDash=[4, 3]
    ).encode(y="y:Q")
    return _base(bars + goal, 200)


def activity_chart(records: list[dict], n: int = 7) -> alt.Chart | None:
    """Steps bars for the last *n* days, colored by the 10k goal, with a goal rule."""
    rows = [
        {"date": r["date"][5:], "steps": r["steps"], "met": (r["steps"] or 0) >= 10000}
        for r in _recent(records, n)
        if r.get("steps") is not None
    ]
    if not rows:
        return None

    df = pd.DataFrame(rows)
    order = list(dict.fromkeys(df["date"]))
    bars = alt.Chart(df).mark_bar().encode(
        x=alt.X("date:N", sort=order, title=None),
        y=alt.Y("steps:Q", title="Steps"),
        color=alt.Color(
            "met:N",
            scale=alt.Scale(domain=[True, False], range=[theme.GOAL_MET, theme.COBALT]),
            legend=alt.Legend(title="≥ 10k", orient="bottom"),
        ),
        tooltip=["date:N", alt.Tooltip("steps:Q", format=",")],
    )
    goal = alt.Chart(pd.DataFrame({"y": [10000]})).mark_rule(
        color=theme.GOAL_MET, strokeDash=[4, 3]
    ).encode(y="y:Q")
    return _base(bars + goal, 190)


_TREND_FIELDS: dict[str, tuple[str, str, str]] = {
    # metric key → (record field, axis title, line color)
    "hrv": ("hrv_rmssd_ms", "HRV (ms)", theme.ACCENT),
    "resting_hr": ("resting_hr", "Resting HR (bpm)", theme.CRIT),
    "sleep_duration": ("sleep_duration_minutes", "Sleep (h)", theme.SLEEP_REM),
}


def trend_line(records: list[dict], metric: str, days: int = 30) -> alt.Chart | None:
    """A 30-day line for HRV / resting HR / sleep duration."""
    field, title, color = _TREND_FIELDS[metric]
    rows = []
    for r in _recent(records, days):
        val = r.get(field)
        if val is None:
            continue
        if metric == "sleep_duration":
            val = val / 60.0
        rows.append({"date": r["date"], "value": val})
    if len(rows) < 2:
        return None

    df = pd.DataFrame(rows)
    line = alt.Chart(df).mark_line(color=color, point=alt.OverlayMarkDef(color=color, size=22)).encode(
        x=alt.X("date:T", title=None),
        y=alt.Y("value:Q", title=title, scale=alt.Scale(zero=False)),
        tooltip=["date:T", alt.Tooltip("value:Q", format=".1f")],
    )
    return _base(line, 170)


# ── Live (rolling buffer of simulated API samples) ───────────────────────────────

def live_line(samples: list[dict[str, Any]], field: str, title: str, color: str) -> alt.Chart | None:
    """Line of a single live signal across the buffered samples (x = device time)."""
    rows = [{"t": s["clock"], "value": s[field]} for s in samples if s.get(field) is not None]
    if len(rows) < 2:
        return None

    df = pd.DataFrame(rows)
    line = alt.Chart(df).mark_line(color=color, point=alt.OverlayMarkDef(color=color, size=18)).encode(
        x=alt.X("t:N", sort=list(df["t"]), title=None, axis=alt.Axis(labelAngle=-40)),
        y=alt.Y("value:Q", title=title, scale=alt.Scale(zero=False)),
        tooltip=["t:N", alt.Tooltip("value:Q", format=".1f")],
    )
    return _base(line, 160)
