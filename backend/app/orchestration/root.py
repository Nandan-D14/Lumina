from __future__ import annotations

from dataclasses import dataclass

from google.adk.agents import ParallelAgent, SequentialAgent

from ..agents.coordinator import build_coordinator_agent
from ..agents.critic import build_critic_agent
from ..agents.entities import build_entities_agent
from ..agents.ingestion import build_ingestion_agent
from ..agents.insights import build_insights_agent
from ..agents.research import build_research_agent
from ..agents.response_assembler import build_response_assembler_agent
from ..agents.visualization import build_visualization_agent
from ..config import Settings


@dataclass(frozen=True)
class AgentGraph:
    root_agent: SequentialAgent
    parallel_agent: ParallelAgent
    finalize_agent: SequentialAgent


def build_agent_graph(settings: Settings) -> AgentGraph:
    research_agent = build_research_agent(settings)
    ingestion_agent = build_ingestion_agent(settings)
    insights_agent = build_insights_agent(settings)
    entities_agent = build_entities_agent(settings)
    visualization_agent = build_visualization_agent(settings)

    parallel_agent = ParallelAgent(
        name="parallel_analysis_agent",
        description="Runs insights, entity extraction, and visualization planning in parallel.",
        sub_agents=[insights_agent, entities_agent, visualization_agent],
    )

    finalize_agent = SequentialAgent(
        name="finalize_agent",
        description="Coordinates, critiques, and assembles the final package.",
        sub_agents=[
            build_coordinator_agent(settings),
            build_critic_agent(settings),
            build_response_assembler_agent(settings),
        ],
    )

    root_agent = SequentialAgent(
        name="insight_orchestrator_root",
        description="Orchestrates research, analysis fan-out, and final package assembly.",
        sub_agents=[ingestion_agent, research_agent, parallel_agent, finalize_agent],
    )
    return AgentGraph(root_agent=root_agent, parallel_agent=parallel_agent, finalize_agent=finalize_agent)
