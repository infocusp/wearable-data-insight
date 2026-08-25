"""Mock attestation / self-reported-conditions generator (ClaimGuard integration, stage B).

Stands in for an EHR / lab-results integration that does not exist, so the demo can make
the half-pager's central claim concrete: **richer context produces a more credible
signal, not a more punitive one.**

Two mechanisms carry that claim:

1. ``consistency_checks`` cross-reference what the applicant *said* against what the
   wearable *observed* — a declared "exercises five times a week" against a measured
   activity-consistency of 34 is flagged ``inconsistent``.
2. ``credibility`` rises as independent evidence accumulates (wearable history depth,
   attestation present, labs present, cross-checks agreeing).

Everything is deterministic per (persona, seed): the same applicant always produces the
same attestation, so screenshots and tests are stable.

This is a **mock** and every surface that renders it must say so.
"""

from __future__ import annotations

import random
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

Verdict = Literal["consistent", "inconsistent", "unverifiable"]

# Condition pool. Deliberately mundane and non-stigmatising: the point of the demo is the
# cross-check mechanic, not a parade of diagnoses.
_CONDITIONS: tuple[tuple[str, str], ...] = (
    ("E78.5", "Raised cholesterol"),
    ("I10", "Hypertension"),
    ("J45", "Mild asthma"),
    ("E11", "Type 2 diabetes"),
    ("M54.5", "Lower back pain"),
)

_LAB_PANELS: tuple[tuple[str, str, str, float, float], ...] = (
    ("Lipids", "Total cholesterol", "mmol/L", 3.5, 6.8),
    ("Lipids", "HDL cholesterol", "mmol/L", 0.9, 2.1),
    ("Metabolic", "Fasting glucose", "mmol/L", 4.0, 7.2),
    ("Metabolic", "HbA1c", "%", 4.8, 7.4),
    ("Renal", "Creatinine", "umol/L", 60.0, 110.0),
)

_REF_RANGES = {
    "Total cholesterol": (0.0, 5.2),
    "HDL cholesterol": (1.0, 3.0),
    "Fasting glucose": (3.9, 5.6),
    "HbA1c": (0.0, 5.7),
    "Creatinine": (60.0, 110.0),
}


class SelfReportedCondition(BaseModel):
    code: str
    label: str
    diagnosed_year: int
    controlled: bool


class LabResult(BaseModel):
    panel: str
    name: str
    value: float
    unit: str
    ref_low: float | None = None
    ref_high: float | None = None
    flag: Literal["normal", "high", "low"] = "normal"


class SelfReported(BaseModel):
    height_cm: int
    weight_kg: float
    bmi: float
    smoker: bool
    alcohol_units_week: int
    exercise_sessions_claimed: int = Field(
        description="Self-declared weekly exercise sessions — the field cross-checked against wearable data."
    )
    conditions: list[SelfReportedCondition] = Field(default_factory=list)
    medications: list[str] = Field(default_factory=list)
    family_history: list[str] = Field(default_factory=list)
    hospitalizations_5y: int = 0


class ConsistencyCheck(BaseModel):
    check: str
    verdict: Verdict
    detail: str


class Credibility(BaseModel):
    score_0_100: int = Field(ge=0, le=100)
    level: Literal["low", "moderate", "high"]
    drivers: list[str] = Field(default_factory=list)


class AttestationBundle(BaseModel):
    attestation_id: str
    user_id: str
    generated_at: date
    seed: int
    is_mock: Literal[True] = Field(
        True, description="Always true. Every rendering surface must label this a mock."
    )
    self_reported: SelfReported
    mock_labs: list[LabResult] = Field(default_factory=list)
    consistency_checks: list[ConsistencyCheck] = Field(default_factory=list)
    credibility: Credibility
    disclaimer: str = (
        "Mock attestation standing in for an electronic health record / laboratory "
        "integration. Generated data — not a real medical record, and not a diagnosis."
    )
    schema_version: str = "1.0"


def _flag_for(name: str, value: float) -> Literal["normal", "high", "low"]:
    ref = _REF_RANGES.get(name)
    if ref is None:
        return "normal"
    low, high = ref
    if value > high:
        return "high"
    if value < low:
        return "low"
    return "normal"


def generate_attestation(
    user_id: str,
    *,
    seed: int = 42,
    generated_at: date | None = None,
    include_labs: bool = True,
    activity_consistency: int | None = None,
    sleep_regularity: int | None = None,
    history_days: int | None = None,
) -> AttestationBundle:
    """Generate a deterministic mock attestation for *user_id*.

    The optional wearable-derived arguments are what make the cross-checks meaningful;
    pass the matching values from ``underwriting.build_underwriting_signals`` so the
    bundle can actually agree or disagree with the observed data.
    """
    rng = random.Random(f"{user_id}:{seed}")
    stamp = generated_at or date.today()

    height = rng.randint(155, 188)
    weight = round(rng.uniform(52, 96), 1)
    bmi = round(weight / ((height / 100) ** 2), 1)
    smoker = rng.random() < 0.18
    claimed_sessions = rng.randint(0, 6)

    conditions: list[SelfReportedCondition] = []
    for code, label in rng.sample(_CONDITIONS, k=rng.randint(0, 2)):
        conditions.append(
            SelfReportedCondition(
                code=code,
                label=label,
                diagnosed_year=rng.randint(2012, stamp.year - 1),
                controlled=rng.random() < 0.75,
            )
        )

    medications = (
        rng.sample(["Statin", "Metformin", "Salbutamol inhaler", "Amlodipine"], k=1)
        if conditions and rng.random() < 0.7
        else []
    )
    family_history = rng.sample(
        ["Cardiovascular disease", "Type 2 diabetes", "Hypertension"], k=rng.randint(0, 2)
    )

    self_reported = SelfReported(
        height_cm=height,
        weight_kg=weight,
        bmi=bmi,
        smoker=smoker,
        alcohol_units_week=rng.randint(0, 16),
        exercise_sessions_claimed=claimed_sessions,
        conditions=conditions,
        medications=medications,
        family_history=family_history,
        hospitalizations_5y=rng.choice([0, 0, 0, 1]),
    )

    labs: list[LabResult] = []
    if include_labs:
        for panel, name, unit, low, high in _LAB_PANELS:
            value = round(rng.uniform(low, high), 1 if unit != "umol/L" else 0)
            ref = _REF_RANGES.get(name, (None, None))
            labs.append(
                LabResult(
                    panel=panel,
                    name=name,
                    value=value,
                    unit=unit,
                    ref_low=ref[0],
                    ref_high=ref[1],
                    flag=_flag_for(name, value),
                )
            )

    # ── Cross-checks: declaration vs observation ──────────────────────────────
    checks: list[ConsistencyCheck] = []

    if activity_consistency is not None:
        # Roughly: each claimed session should show up as observed consistency.
        expected_floor = min(85, 25 + 11 * claimed_sessions)
        if claimed_sessions >= 4 and activity_consistency < expected_floor - 15:
            checks.append(
                ConsistencyCheck(
                    check="Declared exercise frequency vs observed activity consistency",
                    verdict="inconsistent",
                    detail=(
                        f"Applicant declared {claimed_sessions} sessions per week, but measured "
                        f"activity consistency is {activity_consistency}/100 — lower than the "
                        "declaration implies. Worth confirming at interview."
                    ),
                )
            )
        else:
            checks.append(
                ConsistencyCheck(
                    check="Declared exercise frequency vs observed activity consistency",
                    verdict="consistent",
                    detail=(
                        f"Declared {claimed_sessions} sessions per week is consistent with a "
                        f"measured activity consistency of {activity_consistency}/100."
                    ),
                )
            )
    else:
        checks.append(
            ConsistencyCheck(
                check="Declared exercise frequency vs observed activity consistency",
                verdict="unverifiable",
                detail="No wearable activity signal supplied for comparison.",
            )
        )

    if sleep_regularity is not None:
        checks.append(
            ConsistencyCheck(
                check="Sleep regularity corroboration",
                verdict="consistent" if sleep_regularity >= 55 else "inconsistent",
                detail=(
                    f"Measured sleep regularity {sleep_regularity}/100"
                    + (
                        " corroborates a stable routine."
                        if sleep_regularity >= 55
                        else " indicates a more irregular routine than a standard declaration assumes."
                    )
                ),
            )
        )

    checks.append(
        ConsistencyCheck(
            check="Smoking status",
            verdict="unverifiable",
            detail=(
                "Wearable data carries no smoking signal. Declared "
                f"{'smoker' if smoker else 'non-smoker'}; verification would require labs or interview."
            ),
        )
    )

    # ── Credibility: evidence accumulation, not a health judgement ────────────
    drivers: list[str] = []
    score = 30
    drivers.append("Baseline: self-declaration only (30).")

    if history_days:
        if history_days >= 60:
            score += 28
            drivers.append(f"+28 — {history_days} days of continuous wearable history.")
        elif history_days >= 30:
            score += 18
            drivers.append(f"+18 — {history_days} days of wearable history.")
        else:
            score += 8
            drivers.append(
                f"+8 — only {history_days} days of wearable history; below the 30-day "
                "threshold for a confident trend."
            )

    if include_labs and labs:
        score += 16
        drivers.append(f"+16 — {len(labs)} laboratory results attached.")

    agreeing = sum(1 for c in checks if c.verdict == "consistent")
    conflicting = sum(1 for c in checks if c.verdict == "inconsistent")
    if agreeing:
        score += 6 * agreeing
        drivers.append(f"+{6 * agreeing} — {agreeing} cross-check(s) corroborated.")
    if conflicting:
        score -= 9 * conflicting
        drivers.append(
            f"-{9 * conflicting} — {conflicting} cross-check(s) disagreed with the declaration."
        )

    score = max(0, min(100, score))
    level: Literal["low", "moderate", "high"] = (
        "high" if score >= 70 else "moderate" if score >= 45 else "low"
    )

    return AttestationBundle(
        attestation_id=f"att_{user_id}_{stamp.isoformat()}",
        user_id=user_id,
        generated_at=stamp,
        seed=seed,
        self_reported=self_reported,
        mock_labs=labs,
        consistency_checks=checks,
        credibility=Credibility(score_0_100=score, level=level, drivers=drivers),
    )
