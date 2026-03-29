from __future__ import annotations

from google.adk.agents import LlmAgent

from ..config import Settings
from ..schemas.domain import InsightsBranch


INSIGHTS_INSTRUCTION = """
You are the insights specialist.
User prompt:
{user_prompt}

Normalized corpus:
{normalized_corpus}

Research context:
{research_branch?}

Extract:
- a concise summary
- the most important findings
- metrics that should appear in the final insight package

Return grounded output only.
"""


def build_insights_agent(settings: Settings) -> LlmAgent:
    return LlmAgent(
        name="insights_agent",
        description="Extracts summary, findings, and key metrics from the normalized corpus.",
        model=settings.default_model,
        instruction=INSIGHTS_INSTRUCTION,
        output_schema=InsightsBranch,
        output_key="insights_branch",
    )
