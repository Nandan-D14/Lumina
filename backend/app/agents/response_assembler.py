from __future__ import annotations

from google.adk.agents import LlmAgent

from ..config import Settings
from ..schemas.responses import InsightPackage


RESPONSE_ASSEMBLER_INSTRUCTION = """
You are the final response assembler.

Analysis id: {analysis_id}
User prompt:
{user_prompt}

Coordinator draft:
{coordinator_draft}

Critic review:
{critic_review}

Research branch:
{research_branch?}

All citations:
{combined_citations_json}

Artifact refs:
{artifact_refs_json}

Rules:
- Produce the final insight package only.
- If critic_review drops visualizations, remove them.
- If critic_review includes a revised summary, use it.
- Keep only grounded insights.
"""


def build_response_assembler_agent(settings: Settings) -> LlmAgent:
    return LlmAgent(
        name="response_assembler_agent",
        description="Produces the final InsightPackage response.",
        model=settings.default_model,
        instruction=RESPONSE_ASSEMBLER_INSTRUCTION,
        output_schema=InsightPackage,
        output_key="final_insight_package",
    )
