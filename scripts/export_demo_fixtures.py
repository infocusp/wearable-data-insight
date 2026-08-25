#!/usr/bin/env python3
"""Export deterministic demo fixtures for ClaimGuard's Prisma seed.

Why a fixture file rather than seeding from the live sidecar:

* ``prisma db seed`` then has **no runtime dependency** on the Python service, so the
  demo can be seeded (and re-seeded in CI) whether or not the sidecar is up;
* the data is reproducible — same inputs, same bytes, so screenshots stay stable;
* the TypeScript seed never has to reimplement the Python generator.

**The date-offset trap this script exists to solve.**  ``synthetic.DEFAULT_ANALYSIS_DATE``
is a fixed 2026-06-17.  Seeding at that date makes every "vs 30d" label read as stale
history and marks every seeded claim stale under ClaimGuard's ``STALE_DAYS`` rule, so
"Today's snapshot" silently becomes a lie.  This script therefore anchors every persona's
final record to a real, explicit *today*.

Usage::

    PYTHONPATH=src python3 scripts/export_demo_fixtures.py
    DEMO_ANALYSIS_DATE=2026-08-25 PYTHONPATH=src python3 scripts/export_demo_fixtures.py \
        --out ../claim-guard/prisma/fixtures/wearable-personas.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wearable_insights.data.synthetic import (  # noqa: E402
    generate_synthetic_profile,
    list_persona_specs,
)
from wearable_insights.driving.drowsiness import assess_drowsiness  # noqa: E402
from wearable_insights.pipeline import build_comparison  # noqa: E402
from wearable_insights.underwriting import build_underwriting_signals  # noqa: E402
from wearable_insights.underwriting_support.attestation import (  # noqa: E402
    generate_attestation,
)
from wearable_insights.wellness.streaks import compute_streaks  # noqa: E402

DEFAULT_SEED = 42

# Per-persona demo intent. `days` is deliberately varied: recovery_decline is given a
# short history so ClaimGuard's low-confidence path is exercised by the seed itself.
PERSONA_PLAN: dict[str, dict[str, Any]] = {
    "recovery_deficit": {
        "days": 90,
        "role": "member_with_motor_claim",
        "demonstrates": "89 clean days then an acute collapse: critical nudge, coach outreach, and a severe-fatigue motor claim.",
        "drowsiness_incident_time": "07:40",
        "continuous_drive_minutes": 75,
    },
    "healthy_consistent": {
        "days": 90,
        "role": "rewards_showcase",
        "demonstrates": "Long all-green streak reaching a discount-eligible tier; the strong-signal underwriting case.",
    },
    "poor_sleep_week": {
        "days": 90,
        "role": "sleep_theme_member",
        "demonstrates": "A sleep-theme nudge earlier in history; sleep-regularity watch at underwriting.",
    },
    "low_activity": {
        "days": 90,
        "role": "activity_theme_member",
        "demonstrates": "Consistently sedentary: activity nudge and a broken streak, without scoring as favourable.",
    },
    "recovery_decline": {
        "days": 22,
        "role": "underwriting_low_confidence",
        "demonstrates": "Only 22 days of history so low_confidence fires; adding the attestation lifts credibility.",
    },
}


def _shift_records(records: list[dict[str, Any]], target_end: date) -> list[dict[str, Any]]:
    """Re-date a series so its final record lands exactly on *target_end*.

    An exact (not rounded-to-weeks) shift is correct here, which is worth recording
    because the opposite looks safer:

    * the generator's weekly cycle is a sinusoid over ``day_index``
      (``_week_sine``), not over the calendar weekday — so no metric is tied to a
      particular day name;
    * the same-weekday baseline selects records where
      ``weekday(d_i) == weekday(d_end)``, and under a uniform shift N that condition is
      ``d_i == d_end (mod 7)`` either way. The selected set is therefore shift-invariant.

    Rounding to whole weeks would only guarantee that the final record lands up to six
    days *before* the intended date — which is precisely what makes "Today's snapshot"
    stale and trips ClaimGuard's 7-day staleness rule.
    """
    if not records:
        return records
    current_end = date.fromisoformat(records[-1]["date"])
    delta_days = (target_end - current_end).days
    if delta_days == 0:
        return records
    return [
        {**record, "date": (date.fromisoformat(record["date"]) + timedelta(days=delta_days)).isoformat()}
        for record in records
    ]


def build_fixture(analysis_date: date, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    meta_by_persona = {spec["persona"]: spec for spec in list_persona_specs()}
    personas: list[dict[str, Any]] = []

    for persona, plan in PERSONA_PLAN.items():
        days = plan["days"]
        # Generate against the engine's own default anchor, then shift into the present so
        # the weekday structure the analytics depend on is preserved exactly.
        raw = generate_synthetic_profile(persona, seed=seed, days=days, end_date=None)
        records = _shift_records(raw["records"], analysis_date)
        profile = {**raw, "records": records}

        effective_end = date.fromisoformat(records[-1]["date"])
        comparison = build_comparison(profile, effective_end)
        streaks = compute_streaks(profile, effective_end)
        signals = build_underwriting_signals(profile, effective_end, window_days=90)
        by_key = {s.key: s.score for s in signals.signals}
        attestation = generate_attestation(
            profile["user_id"],
            seed=seed,
            generated_at=effective_end,
            include_labs=True,
            activity_consistency=by_key.get("activity_consistency"),
            sleep_regularity=by_key.get("sleep_regularity"),
            history_days=len(records),
        )

        entry: dict[str, Any] = {
            "persona": persona,
            "role": plan["role"],
            "demonstrates": plan["demonstrates"],
            # The seed tuple ClaimGuard persists on WearableProfile — this is the whole
            # persistence story for wearable history.
            "profile_ref": {
                "persona": persona,
                "engine_user_id": profile["user_id"],
                "seed": seed,
                "days": days,
                "end_date": effective_end.isoformat(),
                "jitter": 0.0,
            },
            "identity": meta_by_persona[persona],
            "record_count": len(records),
            "first_date": records[0]["date"],
            "last_date": records[-1]["date"],
            "data_quality": comparison.data_quality.model_dump(mode="json"),
            "streaks": {
                "current_streak": streaks.current_streak,
                "longest_streak": streaks.longest_streak,
                "tier": streaks.tier,
                "next_tier": streaks.next_tier,
                "days_to_next_tier": streaks.days_to_next_tier,
                "discount_eligible": streaks.discount_eligible,
                "discount_pct_suggested": streaks.discount_pct_suggested,
                "pillar_streaks": streaks.pillar_streaks,
            },
            "underwriting": signals.model_dump(mode="json"),
            "attestation": attestation.model_dump(mode="json"),
        }

        incident_time = plan.get("drowsiness_incident_time")
        if incident_time:
            incident_at = f"{effective_end.isoformat()}T{incident_time}"
            assessment = assess_drowsiness(
                profile,
                incident_at,
                continuous_drive_minutes=plan.get("continuous_drive_minutes", 0),
            )
            entry["drowsiness"] = assessment.model_dump(mode="json")

        personas.append(entry)

    return {
        "generated_by": "scripts/export_demo_fixtures.py",
        "engine_version": os.environ.get(
            "WEARABLE_ENGINE_VERSION", "005-claimguard-integration"
        ),
        "schema_version": "1.0",
        "seed": seed,
        "analysis_date": analysis_date.isoformat(),
        "note": (
            "Deterministic demo fixtures. Regenerate with scripts/export_demo_fixtures.py "
            "whenever the demo date moves; every persona's last record is anchored to "
            "analysis_date so 'today' is real."
        ),
        "personas": personas,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default="../claim-guard/prisma/fixtures/wearable-personas.json",
        help="Destination JSON path (relative to this repo root).",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--date",
        default=os.environ.get("DEMO_ANALYSIS_DATE"),
        help="Demo 'today' (YYYY-MM-DD). Defaults to $DEMO_ANALYSIS_DATE, else the real today.",
    )
    args = parser.parse_args()

    analysis_date = (
        datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()
    )
    fixture = build_fixture(analysis_date, seed=args.seed)

    out = Path(args.out)
    if not out.is_absolute():
        out = (Path(__file__).resolve().parents[1] / out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote {out}")
    print(f"  analysis_date : {fixture['analysis_date']}")
    for entry in fixture["personas"]:
        streaks = entry["streaks"]
        print(
            f"  {entry['persona']:20s} {entry['record_count']:3d} days "
            f"[{entry['first_date']} -> {entry['last_date']}] "
            f"streak={streaks['current_streak']:3d} tier={str(streaks['tier']):8s} "
            f"consistency={entry['underwriting']['composite']['consistency']:3d} "
            f"credibility={entry['attestation']['credibility']['score_0_100']:3d}"
            + (f" drowsiness={entry['drowsiness']['level']}" if "drowsiness" in entry else "")
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
