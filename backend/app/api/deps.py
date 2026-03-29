from __future__ import annotations

from functools import lru_cache

from ..config import get_settings
from ..services.export_service import ExportService
from ..services.orchestrator import InsightOrchestrator


@lru_cache
def get_orchestrator() -> InsightOrchestrator:
    return InsightOrchestrator(get_settings())


def get_export_service() -> ExportService:
    orchestrator = get_orchestrator()
    return ExportService(orchestrator.repository)
