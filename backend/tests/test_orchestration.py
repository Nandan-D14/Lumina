from __future__ import annotations

from google.adk.agents import ParallelAgent, SequentialAgent

from backend.app.config import get_settings
from backend.app.orchestration.pipelines import should_run_research
from backend.app.orchestration.root import build_agent_graph
from backend.app.schemas.requests import AnalyzeRequest
from backend.app.schemas.domain import TextSourceInput, UrlSourceInput


def test_should_run_research() -> None:
    request = AnalyzeRequest(
        prompt="Find current revenue",
        sources=[TextSourceInput(type="text", text="Revenue data")],
        options={"allow_web_research": True, "allow_scraping": True, "max_visualizations": 2},
    )
    assert should_run_research(request) is True


def test_should_run_research_for_url_sources() -> None:
    request = AnalyzeRequest(
        prompt="Summarize this page",
        sources=[UrlSourceInput(type="url", url="https://example.com")],
        options={"allow_web_research": False, "allow_scraping": True, "max_visualizations": 2},
    )
    assert should_run_research(request) is True


def test_agent_graph_shape() -> None:
    graph = build_agent_graph(get_settings())
    assert isinstance(graph.root_agent, SequentialAgent)
    assert isinstance(graph.parallel_agent, ParallelAgent)
    assert isinstance(graph.finalize_agent, SequentialAgent)
