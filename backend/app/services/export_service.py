from __future__ import annotations

import csv
import io
import json

from fastapi import HTTPException

from ..schemas.responses import InsightPackage
from .analysis_repository import AnalysisRepository
from .artifact_store import ArtifactContext


class ExportService:
    def __init__(self, repository: AnalysisRepository) -> None:
        self._repository = repository

    async def build_export(self, analysis_id: str, fmt: str, artifacts: ArtifactContext) -> tuple[str, str, str]:
        stored = self._repository.get(analysis_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="Analysis not found.")

        payload_text = await artifacts.load_text(stored.filename, stored.version)
        package = InsightPackage.model_validate_json(payload_text)

        if fmt == "json":
            content = json.dumps(package.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
            export_ref = await artifacts.save_text(f"exports/{analysis_id}.json", content, "application/json")
            return content, "application/json", export_ref.name

        if fmt == "csv":
            buffer = io.StringIO(newline="")
            writer = csv.writer(buffer)
            writer.writerow(["summary", "chart_type", "label", "value"])
            chart_found = False
            for visualization in package.visualizations:
                if visualization.kind in {"bar", "line", "pie"} and visualization.labels and visualization.values:
                    chart_found = True
                    for label, value in zip(visualization.labels, visualization.values):
                        writer.writerow([package.summary, visualization.kind, label, value])
                    break
            if not chart_found:
                raise HTTPException(status_code=422, detail="Stored analysis does not contain a chart-compatible visualization.")
            content = buffer.getvalue()
            export_ref = await artifacts.save_text(f"exports/{analysis_id}.csv", content, "text/csv")
            return content, "text/csv; charset=utf-8", export_ref.name

        raise HTTPException(status_code=400, detail="Unsupported export format.")
