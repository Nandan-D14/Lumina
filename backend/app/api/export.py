from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from ..schemas.requests import ExportRequest
from ..services.export_service import ExportService
from ..services.orchestrator import InsightOrchestrator
from .deps import get_export_service, get_orchestrator

router = APIRouter(prefix="/api/v1", tags=["export"])


@router.post("/export")
async def export_analysis(
    request: ExportRequest,
    orchestrator: InsightOrchestrator = Depends(get_orchestrator),
    export_service: ExportService = Depends(get_export_service),
) -> Response:
    orchestrator.ensure_google_auth()
    artifact_context = orchestrator.artifact_context_for(request.analysis_id)
    payload, media_type, filename = await export_service.build_export(request.analysis_id, request.format, artifact_context)
    return Response(
        content=payload,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename.split("/")[-1]}"'},
    )
