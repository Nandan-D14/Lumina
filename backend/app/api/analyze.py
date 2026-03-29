from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ..schemas.requests import AnalyzeRequest
from ..schemas.responses import InsightPackage
from ..services.orchestrator import InsightOrchestrator
from .deps import get_orchestrator

router = APIRouter(prefix="/api/v1", tags=["analysis"])


@router.post("/analyze", response_model=InsightPackage)
async def analyze(
    request: AnalyzeRequest,
    orchestrator: InsightOrchestrator = Depends(get_orchestrator),
) -> InsightPackage:
    return await orchestrator.analyze(request)

@router.post("/analyze/stream")
async def analyze_stream(
    request: AnalyzeRequest,
    orchestrator: InsightOrchestrator = Depends(get_orchestrator),
):
    return StreamingResponse(
        orchestrator.analyze_stream(request),
        media_type="application/x-ndjson"
    )
