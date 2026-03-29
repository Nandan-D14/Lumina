from __future__ import annotations

from google.adk.agents import LlmAgent

from ..config import Settings
from ..schemas.domain import EntitiesBranch


ENTITIES_INSTRUCTION = """
You are the entity extraction specialist.
User prompt:
{user_prompt}

Normalized corpus:
{normalized_corpus}

Research context:
{research_branch?}

Extract entities that matter for analysis, including organizations, people, products, locations, or named metrics.
Each entity must have a specific type and an optional value only when grounded in the sources.
"""


def build_entities_agent(settings: Settings) -> LlmAgent:
    return LlmAgent(
        name="entities_agent",
        description="Extracts structured entities from the analysis corpus.",
        model=settings.default_model,
        instruction=ENTITIES_INSTRUCTION,
        output_schema=EntitiesBranch,
        output_key="entities_branch",
    )
