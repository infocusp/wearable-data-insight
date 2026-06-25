"""Guard test: the deterministic daily pipeline must not depend on the live layer (SC-006, FR-012).

The live anomaly/feed layer reads the live buffer, but the daily-summary pipeline
(comparison + the daily nudge pipeline) must remain independent of it so its results are
unchanged by this feature.
"""

from __future__ import annotations

from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "wearable_insights"


def test_daily_pipeline_does_not_import_live_layer() -> None:
    for module in ("pipeline.py", "comparison.py"):
        source = (_SRC / module).read_text(encoding="utf-8")
        assert "live_anomaly" not in source, f"{module} must not import live_anomaly"
        assert "data.live" not in source and "data import live" not in source, (
            f"{module} must not import the live feed simulator"
        )
