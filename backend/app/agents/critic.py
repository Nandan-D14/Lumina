from __future__ import annotations

from google.adk.agents import LlmAgent

from ..config import Settings
from ..schemas.domain import CriticReview


CRITIC_INSTRUCTION = """
You are the critic for the draft insight package.

Draft:
{coordinator_draft}

Research branch:
{research_branch?}

Available citations:
{combined_citations_json}

Review goals:
- reject unsupported claims
- flag visualizations that are not grounded
- keep the package concise and accurate
- revise the summary only when necessary

If the draft is acceptable, approve it with no issues.
"""


def build_critic_agent(settings: Settings) -> LlmAgent:
    return LlmAgent(
        name="critic_agent",
        description="Reviews the merged draft for grounding and quality issues.",
        model=settings.default_model,
        instruction=CRITIC_INSTRUCTION,
        output_schema=CriticReview,
        output_key="critic_review",
    )
