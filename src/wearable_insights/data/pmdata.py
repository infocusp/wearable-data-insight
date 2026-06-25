"""PMData Fitbit loader — maps raw Fitbit exports to CanonicalDailyRecord dicts.

Each subject directory (e.g. pmdata/p02/fitbit/) contains:
  sleep.json            — per-night sleep summary (mainSleep=True entries only)
  sleep_score.csv       — Fitbit sleep score + resting HR per night
  resting_heart_rate.json — daily RHR (one value per day)
  steps.json            — intraday 1-min steps (aggregated to daily totals here)
  very_active_minutes.json / moderately_active_minutes.json — daily activity
  lightly_active_minutes.json, sedentary_minutes.json — (loaded but not used in model)

Fields NOT available in this Fitbit export (will be None):
  hrv_rmssd_ms   — Fitbit does not export RMSSD in this dataset
  stress_score   — no stress API in this export
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

PMDATA_SUBJECTS = [f"p{i:02d}" for i in range(1, 17)]


def _read_json(path: Path) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def _load_sleep(fitbit_dir: Path) -> dict[str, dict[str, Any]]:
    """Return dict keyed by dateOfSleep (the wake date) with sleep metrics."""
    path = fitbit_dir / "sleep.json"
    if not path.exists():
        return {}
    records: dict[str, dict] = {}
    for rec in _read_json(path):
        if not rec.get("mainSleep", True):
            continue
        date_str: str = rec["dateOfSleep"]
        start: str = rec.get("startTime", "")
        # startTime like '2019-11-05 23:21:00' — extract HH:MM
        bedtime: str | None = start[11:16] if len(start) >= 16 else None
        levels = rec.get("levels", {}).get("summary", {})
        deep = levels.get("deep", {}).get("minutes")
        rem = levels.get("rem", {}).get("minutes")
        records[date_str] = {
            "sleep_duration_minutes": rec.get("minutesAsleep"),
            "bedtime": bedtime,
            "deep_sleep_minutes": deep,
            "rem_sleep_minutes": rem,
        }
    return records


def _load_sleep_score(fitbit_dir: Path) -> dict[str, int]:
    """Return dict keyed by wake-date string → overall_score (int)."""
    path = fitbit_dir / "sleep_score.csv"
    if not path.exists():
        return {}
    result: dict[str, int] = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            ts = row.get("timestamp", "")
            if not ts:
                continue
            date_str = ts[:10]  # ISO prefix → YYYY-MM-DD
            score_raw = row.get("overall_score", "")
            if score_raw:
                result[date_str] = int(score_raw)
    return result


def _load_daily_float(path: Path) -> dict[str, float]:
    """Generic daily-granularity JSON: {dateTime, value} list → date → float."""
    if not path.exists():
        return {}
    result: dict[str, float] = {}
    for rec in _read_json(path):
        date_str = str(rec["dateTime"])[:10]
        try:
            val = float(rec["value"])
        except (TypeError, ValueError):
            continue
        result[date_str] = val
    return result


def _load_resting_hr(fitbit_dir: Path) -> dict[str, float]:
    """Return date → resting HR (bpm). Skips zero-value placeholder entries."""
    path = fitbit_dir / "resting_heart_rate.json"
    if not path.exists():
        return {}
    result: dict[str, float] = {}
    for rec in _read_json(path):
        date_str = str(rec["dateTime"])[:10]
        val = rec.get("value", {}).get("value", 0.0)
        if val and float(val) > 0:
            result[date_str] = float(val)
    return result


def _load_steps_daily(fitbit_dir: Path) -> dict[str, int]:
    """Aggregate intraday (1-min) steps to daily totals."""
    path = fitbit_dir / "steps.json"
    if not path.exists():
        return {}
    totals: dict[str, int] = defaultdict(int)
    for rec in _read_json(path):
        date_str = str(rec["dateTime"])[:10]
        try:
            totals[date_str] += int(rec["value"])
        except (TypeError, ValueError):
            pass
    return dict(totals)


def _load_active_minutes_daily(fitbit_dir: Path) -> dict[str, int]:
    """Sum very_active_minutes + moderately_active_minutes per day."""
    very = _load_daily_float(fitbit_dir / "very_active_minutes.json")
    moderate = _load_daily_float(fitbit_dir / "moderately_active_minutes.json")
    all_dates = set(very) | set(moderate)
    return {d: int(very.get(d, 0) + moderate.get(d, 0)) for d in all_dates}


def _build_record(
    subject_id: str,
    date_str: str,
    sleep: dict[str, Any] | None,
    sleep_score: int | None,
    rhr: float | None,
    steps: int | None,
    active_minutes: int | None,
) -> dict[str, Any]:
    missing: list[str] = []

    def _m(field: str, val: Any) -> Any:
        if val is None:
            missing.append(field)
        return val

    slp = sleep or {}
    return {
        "user_id": subject_id,
        "date": date_str,
        "sleep_duration_minutes": _m("sleep_duration_minutes", slp.get("sleep_duration_minutes")),
        "sleep_score": _m("sleep_score", sleep_score),
        "deep_sleep_minutes": _m("deep_sleep_minutes", slp.get("deep_sleep_minutes")),
        "rem_sleep_minutes": _m("rem_sleep_minutes", slp.get("rem_sleep_minutes")),
        "bedtime": slp.get("bedtime"),  # allowed to be None without flagging
        "resting_hr": _m("resting_hr", int(round(rhr)) if rhr is not None else None),
        "hrv_rmssd_ms": None,   # not available in this Fitbit export
        "stress_score": None,   # not available in this Fitbit export
        "steps": _m("steps", steps),
        "active_minutes": _m("active_minutes", active_minutes),
        "missing_fields": missing,
        "invalid_fields": [],
    }


def load_pmdata_subject(
    subject_id: str,
    pmdata_root: str | Path,
    *,
    start_date: str | date | None = None,
    end_date: str | date | None = None,
) -> dict[str, Any]:
    """Load one PMData subject's Fitbit data as a canonical profile dict.

    Returns a dict compatible with ``UserProfile`` / ``build_comparison``:
    ``{"user_id": ..., "records": [...]}``

    Args:
        subject_id:   Subject folder name, e.g. ``"p02"``.
        pmdata_root:  Path to the pmdata root directory.
        start_date:   Inclusive lower bound on dates to include (optional).
        end_date:     Inclusive upper bound on dates to include (optional).
    """
    fitbit_dir = Path(pmdata_root) / subject_id / "fitbit"
    if not fitbit_dir.exists():
        raise FileNotFoundError(f"Fitbit directory not found: {fitbit_dir}")

    sleep_by_date = _load_sleep(fitbit_dir)
    scores_by_date = _load_sleep_score(fitbit_dir)
    rhr_by_date = _load_resting_hr(fitbit_dir)
    steps_by_date = _load_steps_daily(fitbit_dir)
    active_by_date = _load_active_minutes_daily(fitbit_dir)

    # Union of all date strings that appear in any source
    all_dates: set[str] = (
        set(sleep_by_date)
        | set(scores_by_date)
        | set(rhr_by_date)
        | set(steps_by_date)
        | set(active_by_date)
    )

    # Filter by requested date range
    if start_date is not None:
        lo = str(start_date) if not isinstance(start_date, str) else start_date
        all_dates = {d for d in all_dates if d >= lo}
    if end_date is not None:
        hi = str(end_date) if not isinstance(end_date, str) else end_date
        all_dates = {d for d in all_dates if d <= hi}

    records = []
    for date_str in sorted(all_dates):
        # Skip dates with no primary sensor data (avoids ghost records from activity
        # files that pre-fill zeros before the device was first worn).
        has_primary = (
            date_str in sleep_by_date
            or date_str in scores_by_date
            or (date_str in rhr_by_date and rhr_by_date[date_str] > 0)
            or (date_str in steps_by_date and steps_by_date[date_str] > 0)
        )
        if not has_primary:
            continue
        rec = _build_record(
            subject_id=subject_id,
            date_str=date_str,
            sleep=sleep_by_date.get(date_str),
            sleep_score=scores_by_date.get(date_str),
            rhr=rhr_by_date.get(date_str),
            steps=steps_by_date.get(date_str),
            active_minutes=active_by_date.get(date_str),
        )
        records.append(rec)

    return {"user_id": subject_id, "records": records}


def available_dates(subject_id: str, pmdata_root: str | Path) -> list[str]:
    """Return sorted list of date strings available for a subject."""
    profile = load_pmdata_subject(subject_id, pmdata_root)
    return [r["date"] for r in profile["records"]]


def pmdata_root_from_env(default: str = "pmdata") -> Path:
    """Resolve the pmdata root: checks PMDATA_ROOT env var, falls back to default."""
    import os
    return Path(os.environ.get("PMDATA_ROOT", default))
