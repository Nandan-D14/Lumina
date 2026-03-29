from __future__ import annotations

import json

from google.adk.tools.tool_context import ToolContext

from ..orchestration import state_keys
from ..schemas.domain import ArtifactRef, Citation


def _load_items(tool_context: ToolContext, key: str) -> list[dict]:
    raw = tool_context.state.get(key)
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


def _store_items(tool_context: ToolContext, key: str, items: list[dict]) -> None:
    tool_context.state[key] = json.dumps(items, ensure_ascii=False)


def append_artifact_ref(tool_context: ToolContext, ref: ArtifactRef) -> None:
    items = _load_items(tool_context, state_keys.ARTIFACT_REFS_JSON)
    payload = ref.model_dump(mode="json")
    if payload not in items:
        items.append(payload)
    _store_items(tool_context, state_keys.ARTIFACT_REFS_JSON, items)


def append_citation(tool_context: ToolContext, citation: Citation) -> None:
    items = _load_items(tool_context, state_keys.COMBINED_CITATIONS_JSON)
    payload = citation.model_dump(mode="json")
    if payload not in items:
        items.append(payload)
    _store_items(tool_context, state_keys.COMBINED_CITATIONS_JSON, items)
