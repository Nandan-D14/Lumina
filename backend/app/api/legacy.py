from __future__ import annotations

from fastapi import APIRouter, Depends

from ..schemas.requests import LegacyRunRequest
from ..schemas.responses import LegacyRunResponse
from ..services.legacy_mapper import to_legacy_response
from ..services.orchestrator import InsightOrchestrator
from .deps import get_orchestrator

router = APIRouter(tags=["legacy"])


@router.post("/run", response_model=LegacyRunResponse)
async def run_legacy(
    request: LegacyRunRequest,
    orchestrator: InsightOrchestrator = Depends(get_orchestrator),
) -> LegacyRunResponse:
    package = await orchestrator.analyze(request.to_analyze_request())
    return to_legacy_response(package)
