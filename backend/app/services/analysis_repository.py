from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StoredAnalysis:
    analysis_id: str
    user_id: str
    session_id: str
    filename: str
    version: int


class AnalysisRepository:
    def __init__(self) -> None:
        self._items: dict[str, StoredAnalysis] = {}

    def save(self, item: StoredAnalysis) -> None:
        self._items[item.analysis_id] = item

    def get(self, analysis_id: str) -> StoredAnalysis | None:
        return self._items.get(analysis_id)
