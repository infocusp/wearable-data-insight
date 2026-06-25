from __future__ import annotations

from collections import defaultdict
from datetime import date
import json

from wearable_insights.data.synthetic import (
    PROFILE_NAMES,
    build_recovery_deficit_snapshot,
    generate_multi_profile_dataset,
    generate_multi_profile_index,
    generate_synthetic_profile,
)


def _serialise(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def test_seeded_profile_is_reproducible() -> None:
    left = generate_synthetic_profile("healthy_consistent", seed=7, days=12, end_date=date(2026, 6, 17))
    right = generate_synthetic_profile("healthy_consistent", seed=7, days=12, end_date=date(2026, 6, 17))
    assert _serialise(left) == _serialise(right)


def test_profile_payload_includes_identity_fields() -> None:
    for name in (*PROFILE_NAMES, "recovery_deficit"):
        profile = generate_synthetic_profile(name, seed=3, days=10, end_date=date(2026, 6, 17))
        assert profile["display_name"], f"{name} missing display_name"
        # DOB is an ISO date string.
        assert date.fromisoformat(profile["dob"])
        assert profile["avatar"].endswith(".svg")


def test_recovery_deficit_snapshot_has_targeted_last_day() -> None:
    profile = build_recovery_deficit_snapshot(seed=11, days=31, end_date=date(2026, 6, 17))
    records = profile["records"]
    assert len(records) == 31

    baseline = records[:-1]
    current = records[-1]

    assert current["sleep_duration_minutes"] < sum(r["sleep_duration_minutes"] for r in baseline if r["sleep_duration_minutes"] is not None) / len(
        [r for r in baseline if r["sleep_duration_minutes"] is not None]
    )
    assert current["stress_score"] > sum(r["stress_score"] for r in baseline if r["stress_score"] is not None) / len(
        [r for r in baseline if r["stress_score"] is not None]
    )


def test_missing_data_fragments_are_short_and_sparse() -> None:
    profile = generate_synthetic_profile("poor_sleep_week", seed=3, days=90, end_date=date(2026, 6, 17))
    records = profile["records"]

    missing_runs: dict[str, list[int]] = defaultdict(list)
    for field in ("sleep_duration_minutes", "sleep_score", "deep_sleep_minutes", "rem_sleep_minutes", "bedtime", "resting_hr", "hrv_rmssd_ms", "stress_score", "steps", "active_minutes"):
        run = 0
        for record in records:
            if record[field] is None:
                run += 1
            elif run:
                missing_runs[field].append(run)
                run = 0
        if run:
            missing_runs[field].append(run)

    assert any(missing_runs.values())
    assert all(run <= 2 for runs in missing_runs.values() for run in runs)
    assert sum(len(record["missing_fields"]) > 0 for record in records) <= 8


def test_multi_profile_dataset_uses_canonical_order() -> None:
    dataset = generate_multi_profile_dataset(seed=21, days=10, end_date=date(2026, 6, 17))
    assert [profile["user_id"] for profile in dataset] == [
        "usr_healthy_consistent",
        "usr_poor_sleep_week",
        "usr_low_activity",
        "usr_recovery_decline",
    ]


def test_multi_profile_index_matches_known_profiles() -> None:
    indexed = generate_multi_profile_index(seed=21, days=5, end_date=date(2026, 6, 17))
    assert sorted(indexed) == sorted(PROFILE_NAMES)
