from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.app.schemas.responses import InsightPackage
from backend.app.schemas.domain import VisualizationSpec
from backend.app.services.legacy_mapper import to_legacy_response


def test_legacy_mapper_success() -> None:
    package = InsightPackage(
        analysis_id="a1",
        summary="Revenue grew.",
        visualizations=[
            VisualizationSpec(
                id="viz-1",
                title="Revenue by quarter",
                kind="bar",
                reason="Best comparison",
                labels=["Q1", "Q2"],
                values=[45, 89],
            )
        ],
    )
    result = to_legacy_response(package)
    assert result.chart_type == "bar"
    assert result.chart_data.values == [45, 89]


def test_legacy_mapper_raises_when_no_chart() -> None:
    package = InsightPackage(analysis_id="a2", summary="No chart")
    with pytest.raises(HTTPException) as exc:
        to_legacy_response(package)
    assert exc.value.status_code == 422
