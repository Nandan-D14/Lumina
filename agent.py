from __future__ import annotations

from backend.app.config import get_settings
from backend.app.orchestration.root import AgentGraph, build_agent_graph


def create_agent_graph() -> AgentGraph:
    return build_agent_graph(get_settings())


root_agent = create_agent_graph().root_agent

__all__ = ["create_agent_graph", "root_agent"]
