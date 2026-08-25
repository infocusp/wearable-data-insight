"""FastAPI surface over the wearable analytics engine (ClaimGuard integration).

Wraps the existing engine without reimplementing any of its math.  Three properties are
load-bearing and every handler upholds them:

**Stateless.**  The service holds no mutable per-user state.  Histories and live buffers
are reconstructed from a seed tuple (``ProfileRef`` / ``LiveCursor``); the one genuinely
mutable thing — live-nudge episode/cooldown state — travels in the request and comes back
in the response for the caller to persist.  The service can therefore restart, scale out,
and be load-balanced without sticky sessions.

**Date-explicit.**  ``date.today()`` is never allowed to run in a request path.  Every
endpoint derives its analysis date from the request, so a response cannot change silently
at UTC midnight or differ between the caller's timezone and the sidecar's.

**Deterministic where it matters.**  Every score, direction, and severity is computed in
Python.  The LLM only ever writes prose about numbers it cannot alter.

Run locally::

    PYTHONPATH=src uvicorn wearable_insights.api:app --reload
"""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from . import live_anomaly
from .api_deps import llm_key_context, require_service_token
from .api_models import (
    AnalyzeRequest,
    ComparisonResponse,
    DrowsinessRequest,
    ErrorResponse,
    HealthResponse,
    LiveSample,
    LiveTickRequest,
    LiveTickResponse,
    NudgeResponse,
    PersonaListResponse,
    ProfileMeta,
    ProfileRef,
    StreakRequest,
    UnderwritingRequest,
    sample_to_model,
)
from .api_profiles import (
    build_baselines,
    build_profile,
    cache_stats,
    persona_meta,
    warm_baselines,
)
from .config import DISCLAIMER, MAX_NUDGES_PER_DAY, WEARABLE_MODEL
from .data.live import LIVE_SIGNALS, seed_buffer, signal_status
from .data.slotted_baselines import day_type, slot_index, slot_label
from .data.synthetic import list_persona_specs
from .driving.drowsiness import DrowsinessAssessment, assess_drowsiness
from .models import ComparisonObject, NudgeSet
from .nudges import generate_nudge_set
from .pipeline import build_comparison, run_nudge_pipeline
from .safety import SafetyError
from .underwriting import UnderwritingSignalSet, build_underwriting_signals
from .underwriting_support.attestation import AttestationBundle, generate_attestation
from .wellness.streaks import StreakSet, compute_streaks

ENGINE_VERSION = os.environ.get("WEARABLE_ENGINE_VERSION", "005-claimguard-integration")
SCHEMA_VERSION = "1.0"

_state: dict[str, Any] = {"baselines_warm": False}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Warm the derived caches so the first real request does not pay for them.

    Warming is best-effort: the caches are derived from pure functions, so a failure here
    costs latency and never correctness.
    """
    anchor = os.environ.get("WEARABLE_WARM_DATE")
    try:
        warm_date = date.fromisoformat(anchor) if anchor else date.today()
        warmed = warm_baselines(warm_date)
        _state["baselines_warm"] = warmed > 0
        _state["warm_date"] = warm_date.isoformat()
    except Exception as exc:  # pragma: no cover — never block startup on a warm failure
        _state["baselines_warm"] = False
        _state["warm_error"] = str(exc)
    yield


# No CORS middleware, deliberately: this service is server-to-server only. Adding CORS
# would be what allows a browser — and therefore an end user — to reach it directly.
app = FastAPI(
    title="Wearable Insights Engine",
    version=SCHEMA_VERSION,
    description=(
        "Deterministic wearable analytics with a bounded LLM narrative layer, exposed for "
        "ClaimGuard. Server-to-server only."
    ),
    lifespan=lifespan,
)


# ── Error mapping ─────────────────────────────────────────────────────────────


def _error(status: int, error: str, detail: str | None = None, **extra: Any) -> JSONResponse:
    payload = ErrorResponse(error=error, detail=detail, **extra).model_dump(exclude_none=True)
    return JSONResponse(status_code=status, content=payload)


@app.exception_handler(SafetyError)
def _handle_safety(_request: Request, exc: SafetyError) -> JSONResponse:
    return _error(422, "safety_rejected", str(exc), violations=exc.violations)


@app.exception_handler(ValueError)
def _handle_value(_request: Request, exc: ValueError) -> JSONResponse:
    # Covers `Unknown model '...'` and `Unknown profile '...'` from the engine.
    return _error(400, "bad_request", str(exc))


@app.exception_handler(RuntimeError)
def _handle_runtime(_request: Request, exc: RuntimeError) -> JSONResponse:
    message = str(exc)
    if "API_KEY" in message or "GCP_PROJECT" in message:
        return _error(503, "llm_unavailable", message)
    return _error(500, "internal_error", message)


# ── Unauthenticated: health only, and it returns no secrets ───────────────────


@app.get("/v1/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        engine_version=ENGINE_VERSION,
        schema_version=SCHEMA_VERSION,
        default_model=WEARABLE_MODEL,
        personas=[spec["persona"] for spec in list_persona_specs()],
        baselines_warm=bool(_state.get("baselines_warm")),
    )


# Router-level dependency so a newly added endpoint cannot forget authentication.
v1 = APIRouter(
    prefix="/v1",
    dependencies=[Depends(require_service_token)],
    responses={401: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)


@v1.get("/personas", response_model=PersonaListResponse, tags=["meta"])
def personas() -> PersonaListResponse:
    return PersonaListResponse(personas=list_persona_specs())  # type: ignore[arg-type]


@v1.get("/diagnostics", tags=["meta"])
def diagnostics() -> dict[str, Any]:
    """Cache occupancy and warm state — operational visibility, no user data."""
    return {"caches": cache_stats(), **{k: v for k, v in _state.items()}}


# ── Helpers shared by the analysis endpoints ──────────────────────────────────


def _profile_meta(ref: ProfileRef, profile: dict[str, Any]) -> ProfileMeta:
    meta = persona_meta(ref.persona)
    records = profile.get("records") or []
    return ProfileMeta(
        user_id=profile.get("user_id", meta["engine_user_id"]),
        persona=ref.persona,
        display_name=profile.get("display_name") or meta["display_name"],
        dob=profile.get("dob") or meta["dob"],
        age=profile.get("age") or meta["age"],
        gender=profile.get("gender") or meta["gender"],
        avatar=profile.get("avatar") or meta["avatar"],
        record_count=len(records),
        first_date=date.fromisoformat(records[0]["date"]) if records else None,
        last_date=date.fromisoformat(records[-1]["date"]) if records else None,
    )


def _record_for(profile: dict[str, Any], analysis_date: date) -> dict[str, Any]:
    target = analysis_date.isoformat()
    records = profile.get("records") or []
    return next(
        (r for r in records if r.get("date") == target), records[-1] if records else {}
    )


# ── Deterministic analysis (no LLM, so no credential required) ────────────────


@v1.post("/comparison", response_model=ComparisonResponse, tags=["analysis"])
def comparison(request: AnalyzeRequest) -> dict[str, Any]:
    """Deterministic layers only: baselines → window comparisons → associations."""
    profile = build_profile(request.profile)
    resolved = request.resolved_analysis_date()
    obj = build_comparison(profile, resolved)
    return {
        "comparison": obj.model_dump(mode="json"),
        "profile_meta": _profile_meta(request.profile, profile).model_dump(mode="json"),
        "engine_version": ENGINE_VERSION,
    }


@v1.post("/underwriting/signals", response_model=UnderwritingSignalSet, tags=["underwriting"])
def underwriting_signals(request: UnderwritingRequest) -> UnderwritingSignalSet:
    """Explainable underwriting signals. Fully deterministic — no narrative in this build.

    The ``narrative`` field stays ``None`` until the separate underwriting safety profile
    is reviewed and enabled; the deterministic signals are useful to an underwriter on
    their own, and shipping them first keeps this surface reviewable in isolation.
    """
    profile = build_profile(request.profile)
    return build_underwriting_signals(
        profile, request.resolved_analysis_date(), window_days=request.window_days
    )


@v1.post("/wellness/streaks", response_model=StreakSet, tags=["wellness"])
def wellness_streaks(request: StreakRequest) -> StreakSet:
    """Reward-side branch: streaks, tier, and discount *eligibility* (never an applied discount)."""
    profile = build_profile(request.profile)
    return compute_streaks(
        profile, request.resolved_analysis_date(), lookback_days=request.lookback_days
    )


@v1.post("/drowsiness/assess", response_model=DrowsinessAssessment, tags=["driving"])
def drowsiness(request: DrowsinessRequest) -> DrowsinessAssessment:
    """Fatigue-risk context for a motor incident. Liability evidence, never fraud evidence."""
    profile = build_profile(request.profile)
    return assess_drowsiness(
        profile,
        request.incident_at,
        window_minutes=request.window_minutes,
        continuous_drive_minutes=request.continuous_drive_minutes,
    )


@v1.post("/attestation/mock", response_model=AttestationBundle, tags=["underwriting"])
def attestation(
    request: UnderwritingRequest,
    include_labs: bool = Query(True),
) -> AttestationBundle:
    """Mock attestation + credibility, cross-checked against this applicant's own signals."""
    profile = build_profile(request.profile)
    resolved = request.resolved_analysis_date()
    signals = build_underwriting_signals(profile, resolved, window_days=request.window_days)
    by_key = {s.key: s.score for s in signals.signals}
    return generate_attestation(
        profile.get("user_id", request.profile.persona),
        seed=request.profile.seed,
        generated_at=resolved,
        include_labs=include_labs,
        activity_consistency=by_key.get("activity_consistency"),
        sleep_regularity=by_key.get("sleep_regularity"),
        history_days=len(profile.get("records") or []),
    )


# ── LLM-backed endpoints ──────────────────────────────────────────────────────


@v1.post(
    "/nudges",
    response_model=NudgeResponse,
    response_model_exclude_none=False,
    tags=["wellness"],
    dependencies=[Depends(llm_key_context)],
)
def nudges(request: AnalyzeRequest) -> dict[str, Any]:
    """Risk-side branch: anomalies → bounded, safety-gated nudge set.

    Always returns 200.  ``comparison`` is deterministic and useful even when the LLM leg
    fails, so an upstream model outage must not cost the caller the analysis as well; the
    failure is reported in ``error`` instead.  A clean day yields an empty nudge set with
    no LLM call at all.
    """
    profile = build_profile(request.profile)
    resolved = request.resolved_analysis_date()

    if request.llm.skip_llm:
        obj = build_comparison(profile, resolved)
        return {
            "comparison": obj.model_dump(mode="json"),
            "nudge_set": NudgeSet(user_id=obj.user_id, analysis_date=resolved).model_dump(mode="json"),
            "error": None,
            "llm_skipped": True,
        }

    result = run_nudge_pipeline(
        profile,
        resolved,
        model=request.llm.model,
        **({"max_retries": request.llm.max_retries} if request.llm.max_retries is not None else {}),
    )
    return {
        "comparison": result.comparison.model_dump(mode="json"),
        "nudge_set": result.nudge_set.model_dump(mode="json") if result.nudge_set else None,
        "error": result.error,
        "max_nudges_per_day": MAX_NUDGES_PER_DAY,
    }


@v1.post(
    "/live/tick",
    response_model=LiveTickResponse,
    tags=["wellness"],
    dependencies=[Depends(llm_key_context)],
)
def live_tick(request: LiveTickRequest) -> dict[str, Any]:
    """Advance the simulated intraday feed one sync and report anything it raised.

    The response carries the *advanced* cursor and the *updated* nudge state, so the
    caller stores what it receives and never performs clock arithmetic or state
    bookkeeping itself.
    """
    profile = build_profile(request.profile)
    resolved = request.resolved_analysis_date()
    cursor = request.cursor

    record = _record_for(profile, resolved)
    baselines = build_baselines(record, resolved)
    dt = cursor.day_type or day_type(resolved.weekday())

    buffer = seed_buffer(
        baselines.flat_anchors, cursor.mode, cursor.device_minute, cursor.points, cursor.step
    )

    detected = live_anomaly.detect_live_anomalies(
        buffer,
        baselines,
        cursor.mode,
        current_minute=cursor.device_minute,
        current_day_type=dt,
    )

    # Episode/cooldown state round-trips as plain JSON rather than living in the service.
    state: dict[str, dict[str, Any]] = {
        code: entry.model_dump() for code, entry in request.nudge_state.items()
    }
    now = request.now if request.now is not None else time.time()
    fresh, state = live_anomaly.filter_new_anomalies(detected, state, now)

    raised: list[dict[str, Any]] = []
    error: str | None = None
    if fresh and request.generate_nudges and not request.llm.skip_llm:
        try:
            synthesized = live_anomaly.synthesize_comparison(
                fresh,
                buffer,
                baselines,
                profile.get("user_id", "unknown"),
                resolved,
                current_minute=cursor.device_minute,
                current_day_type=dt,
            )
            # In wake-up mode the detector remaps HRV depression to a sleep-quality
            # anomaly, so ground the LLM in the real overnight sleep section rather than
            # in live HRV alone — mirroring the dashboard's behaviour.
            if cursor.mode == "wake-up":
                daily = build_comparison(profile, resolved)
                if daily.sleep:
                    synthesized = synthesized.model_copy(update={"sleep": daily.sleep})
            nudge_set = generate_nudge_set(
                anomalies=fresh,
                comparison=synthesized,
                generate_fn=None if not request.llm.model else None,
            )
            raised = [n.model_dump(mode="json") for n in nudge_set.nudges]
        except Exception as exc:
            # A generation failure must never stop the live feed; report and carry on.
            error = f"Nudge generation failed: {exc}"

    latest = buffer[-1] if buffer else {}
    statuses = {
        sig["key"]: signal_status(sig["key"], latest.get(sig["key"])) for sig in LIVE_SIGNALS
    }

    advanced = cursor.model_copy(
        update={"device_minute": (cursor.device_minute + cursor.step) % 1440, "day_type": dt}
    )

    return {
        "samples": [
            sample_to_model(
                s, {k: signal_status(k, s.get(k)) for k in (sig["key"] for sig in LIVE_SIGNALS)}
            ).model_dump(mode="json")
            for s in buffer
        ],
        "latest": sample_to_model(latest, statuses).model_dump(mode="json") if latest else None,
        "anomalies": [a.model_dump(mode="json") for a in detected],
        "new_anomalies": [a.model_dump(mode="json") for a in fresh],
        "nudges": raised,
        "nudge_state": state,
        "cursor": advanced.model_dump(mode="json"),
        "slot": slot_index(cursor.device_minute),
        "slot_label": slot_label(slot_index(cursor.device_minute)),
        "day_type": dt,
        "error": error,
    }


app.include_router(v1)


# ── Compatibility aliases for the frozen 001 contract ─────────────────────────
# The 001 spec predates this integration. Its operation semantics are honoured where they
# survive; `/ingest` does not, because it presupposes server-side record storage and this
# service deliberately stores nothing.

legacy = APIRouter(
    tags=["legacy-001"],
    dependencies=[Depends(require_service_token)],
    responses={401: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)


@legacy.get("/comparison-json", response_model=ComparisonResponse)
def legacy_comparison(
    persona: str = Query(...),
    end_date: date = Query(...),
    analysis_date: date | None = Query(None),
    seed: int = Query(42),
    days: int = Query(90),
) -> dict[str, Any]:
    request = AnalyzeRequest(
        profile=ProfileRef(persona=persona, seed=seed, days=days, end_date=end_date),  # type: ignore[arg-type]
        analysis_date=analysis_date,
    )
    return comparison(request)


@legacy.post("/generate-insights", response_model=NudgeResponse)
def legacy_generate_insights(request: AnalyzeRequest) -> dict[str, Any]:
    return nudges(request)


@legacy.post("/ingest")
def legacy_ingest() -> JSONResponse:
    return _error(
        501,
        "not_implemented",
        "This service is stateless by design and stores no records. Send a ProfileRef "
        "(persona + seed + end_date) to /v1/comparison instead; the history is "
        "reconstructed deterministically.",
    )


app.include_router(legacy)
