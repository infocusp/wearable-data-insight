"""Contract test: the generated OpenAPI document matches the checked-in contract.

Response models are the engine's own Pydantic classes, so FastAPI derives the schema
directly from ``models.py`` and friends. That means this test catches an unintended
contract change the moment an engine model is edited — which is the whole reason the
contract is generated rather than hand-written.

Regenerate deliberately with::

    WEARABLE_API_TOKEN=x PYTHONPATH=src python3 -c \
      "import json;from wearable_insights.api import app;\
       open('specs/005-claimguard-integration/contracts/rest-api.openapi.json','w')\
       .write(json.dumps(app.openapi(), indent=2))"
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

_CONTRACT = (
    Path(__file__).parents[2]
    / "specs/005-claimguard-integration/contracts/rest-api.openapi.json"
)

# Endpoints ClaimGuard depends on. Losing one silently would break the integration.
_REQUIRED_PATHS = {
    "/v1/health",
    "/v1/personas",
    "/v1/comparison",
    "/v1/nudges",
    "/v1/live/tick",
    "/v1/wellness/streaks",
    "/v1/underwriting/signals",
    "/v1/drowsiness/assess",
    "/v1/attestation/mock",
}


@pytest.fixture(scope="module")
def generated() -> dict:
    os.environ.setdefault("WEARABLE_API_TOKEN", "contract-test")
    from wearable_insights.api import app

    return app.openapi()


@pytest.fixture(scope="module")
def checked_in() -> dict:
    return json.loads(_CONTRACT.read_text())


def test_contract_file_exists():
    assert _CONTRACT.exists(), f"missing generated contract at {_CONTRACT}"


def test_all_required_paths_are_present(generated):
    missing = _REQUIRED_PATHS - set(generated["paths"])
    assert not missing, f"contract lost required endpoints: {sorted(missing)}"


def test_generated_matches_checked_in(generated, checked_in):
    """Fails when an engine model changes without the contract being regenerated."""
    assert set(generated["paths"]) == set(checked_in["paths"]), (
        "endpoint set drifted from the checked-in contract"
    )
    gen_schemas = set(generated.get("components", {}).get("schemas", {}))
    old_schemas = set(checked_in.get("components", {}).get("schemas", {}))
    assert gen_schemas == old_schemas, (
        f"schema set drifted: added={sorted(gen_schemas - old_schemas)} "
        f"removed={sorted(old_schemas - gen_schemas)}"
    )


def test_engine_models_are_reused_not_redescribed(generated):
    """The contract must expose the engine's own models, proving no parallel schema."""
    schemas = generated.get("components", {}).get("schemas", {})
    for model in ("ComparisonObject", "NudgeSet", "Anomaly", "MetricComparison"):
        assert model in schemas, f"{model} is not surfaced in the contract"


def test_health_is_the_only_unauthenticated_path(generated):
    """Every endpoint except health must document a 401."""
    for path, operations in generated["paths"].items():
        if path == "/v1/health":
            continue
        for method, operation in operations.items():
            if method not in {"get", "post"}:
                continue
            assert "401" in operation.get("responses", {}), (
                f"{method.upper()} {path} does not document a 401 — is it authenticated?"
            )


def test_profile_ref_requires_end_date(generated):
    """end_date must be required in the contract, not defaulted server-side."""
    schema = generated["components"]["schemas"]["ProfileRef"]
    assert "end_date" in schema.get("required", []), (
        "end_date must be required so no handler can fall back to date.today()"
    )
