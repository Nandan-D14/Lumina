from __future__ import annotations

from fastapi import HTTPException

from ..schemas.responses import InsightPackage, LegacyChartData, LegacyRunResponse


def to_legacy_response(package: InsightPackage) -> LegacyRunResponse:
    for visualization in package.visualizations:
        if visualization.kind in {"bar", "line", "pie"} and visualization.labels and visualization.values:
            return LegacyRunResponse(
                summary=package.summary,
                chart_type=visualization.kind,
                chart_data=LegacyChartData(labels=visualization.labels, values=visualization.values),
            )
    raise HTTPException(status_code=422, detail="Could not extract chartable data from the input.")
