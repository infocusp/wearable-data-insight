"""Anthropic tool definitions and execution for the wearable chatbot.

The LLM can call ``get_wearable_period_summary`` whenever the user asks about
trends, improvements, or comparisons over a time range.  The tool is executed
server-side and the result is injected back into the conversation before the
model produces its final reply.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from ..models import ComparisonObject

# ── Metric field mapping ──────────────────────────────────────────────────────

_METRIC_TO_RECORD_FIELD: dict[str, str] = {
    "sleep_duration": "sleep_duration_minutes",
    "sleep_score": "sleep_score",
    "deep_sleep": "deep_sleep_minutes",
    "rem_sleep": "rem_sleep_minutes",
    "resting_hr": "resting_hr",
    "hrv": "hrv_rmssd_ms",
    "stress": "stress_score",
    "steps": "steps",
    "active_minutes": "active_minutes",
}

_ALL_METRICS = list(_METRIC_TO_RECORD_FIELD.keys())

# Maps period enum → ComparisonObject window attribute name (pre-computed).
_PERIOD_TO_WINDOW: dict[str, str] = {
    "last_7_days": "weekly",
    "last_30_days": "monthly",
    "last_60_days": "sixty_day",
    "last_90_days": "ninety_day",
}

_PERIOD_TO_DAYS: dict[str, int] = {
    "last_7_days": 7,
    "last_14_days": 14,
    "last_30_days": 30,
    "last_60_days": 60,
    "last_90_days": 90,
}

# ── Tool schema (Anthropic format) ────────────────────────────────────────────

TOOLS: list[dict] = [
    {
        "name": "get_wearable_period_summary",
        "description": (
            "Retrieve aggregated wearable health metrics for a requested time period. "
            "Call this tool whenever the user asks about trends, improvements, "
            "or comparisons over a time range — e.g. 'how have I been doing this week', "
            "'has my sleep improved since last month', 'show me my activity over the past 7 days'. "
            "Returns pre-computed baseline comparisons plus a recent-vs-prior period breakdown "
            "computed from the user's raw daily records."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["last_7_days", "last_14_days", "last_30_days", "last_60_days", "last_90_days"],
                    "description": "The time window to summarise.",
                },
                "metrics": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": _ALL_METRICS,
                    },
                    "description": (
                        "Specific metrics to include in the summary.  "
                        "Omit (or pass an empty list) to include all available metrics."
                    ),
                },
            },
            "required": ["period"],
        },
    }
]


# ── Computation helpers ───────────────────────────────────────────────────────


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _pct(new: float | None, old: float | None) -> float | None:
    if new is None or old is None or old == 0:
        return None
    return (new - old) / old * 100


def _collect_values(records: list[dict], field: str, from_date: date, to_date: date) -> list[float]:
    out: list[float] = []
    for r in records:
        r_date = date.fromisoformat(r["date"])
        if from_date <= r_date <= to_date:
            v = r.get(field)
            if v is not None:
                out.append(float(v))
    return out


# ── Tool executor ─────────────────────────────────────────────────────────────


def _execute_period_summary(
    period: str,
    metrics: list[str] | None,
    comparison: ComparisonObject,
    profile_dict: dict,
) -> str:
    n_days = _PERIOD_TO_DAYS.get(period, 30)
    window_key = _PERIOD_TO_WINDOW.get(period)  # None for last_14_days
    analysis_date = comparison.analysis_date
    target_metrics = metrics if metrics else _ALL_METRICS

    # Date boundaries for the recent period and the prior period of equal length
    recent_end = analysis_date
    recent_start = analysis_date - timedelta(days=n_days - 1)
    prior_end = recent_start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=n_days - 1)

    records: list[dict] = profile_dict.get("records", [])
    all_sections = {**comparison.sleep, **comparison.heart_health, **comparison.activity}

    sections_out: list[dict] = []
    for metric in target_metrics:
        mc = all_sections.get(metric)
        if mc is None:
            continue

        field = _METRIC_TO_RECORD_FIELD[metric]
        recent_vals = _collect_values(records, field, recent_start, recent_end)
        prior_vals = _collect_values(records, field, prior_start, prior_end)
        recent_avg = _avg(recent_vals)
        prior_avg = _avg(prior_vals)
        period_vs_prior_pct = _pct(recent_avg, prior_avg)

        entry: dict = {
            "metric": metric,
            "today": mc.current_value,
            "recent_period": {
                "from": recent_start.isoformat(),
                "to": recent_end.isoformat(),
                "days_with_data": len(recent_vals),
                "average": round(recent_avg, 2) if recent_avg is not None else None,
            },
            "prior_period": {
                "from": prior_start.isoformat(),
                "to": prior_end.isoformat(),
                "days_with_data": len(prior_vals),
                "average": round(prior_avg, 2) if prior_avg is not None else None,
            },
            "change_recent_vs_prior_pct": (
                round(period_vs_prior_pct, 1) if period_vs_prior_pct is not None else None
            ),
        }

        # Include pre-computed window data when available (gives evaluation tags)
        if window_key:
            window = getattr(mc, window_key)
            entry["baseline_window"] = {
                "window": window_key,
                "baseline_value": window.baseline_value,
                "today_vs_baseline_pct": window.percentage_change,
                "trend": window.trend,
                "evaluation_tag": window.evaluation_tag,
            }

        sections_out.append(entry)

    result = {
        "user_id": comparison.user_id,
        "analysis_date": analysis_date.isoformat(),
        "period_requested": period,
        "metrics": sections_out,
        "note": (
            "recent_period includes today; prior_period is the immediately preceding "
            "window of the same length. baseline_window (when present) uses pre-computed "
            "baselines where today is compared against the rolling mean before today."
        ),
    }
    return json.dumps(result, indent=2)


def execute_tool(
    name: str,
    tool_input: dict,
    comparison: ComparisonObject,
    profile_dict: dict,
) -> str:
    """Dispatch a tool call from the LLM and return the result as a string."""
    if name == "get_wearable_period_summary":
        return _execute_period_summary(
            period=tool_input.get("period", "last_7_days"),
            metrics=tool_input.get("metrics") or None,
            comparison=comparison,
            profile_dict=profile_dict,
        )
    return json.dumps({"error": f"Unknown tool: {name}"})
