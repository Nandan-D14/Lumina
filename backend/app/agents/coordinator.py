from __future__ import annotations

from google.adk.agents import LlmAgent

from ..config import Settings
from ..schemas.domain import CoordinatorDraft


COORDINATOR_INSTRUCTION = """
You are the coordinator that merges branch outputs into a draft insight package.

User prompt:
{user_prompt}

Tables from ingestion:
{normalized_tables_json}

Research branch:
{research_branch?}

Insights branch:
{insights_branch}

Entities branch:
{entities_branch}

Visualizations branch:
{visualizations_branch}

Create a coherent draft with:
- one final summary
- consolidated insights
- deduplicated metrics
- deduplicated entities
- relevant tables
- relevant visualizations
"""


def build_coordinator_agent(settings: Settings) -> LlmAgent:
    return LlmAgent(
        name="coordinator_agent",
        description="Merges specialist branch outputs into a single coordinated draft.",
        model=settings.default_model,
        instruction=COORDINATOR_INSTRUCTION,
        output_schema=CoordinatorDraft,
        output_key="coordinator_draft",
    )
