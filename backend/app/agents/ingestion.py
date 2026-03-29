from __future__ import annotations

from google.adk.agents import LlmAgent

from ..config import Settings


INGESTION_INSTRUCTION = """
You are the ingestion specialist.
User prompt:
{user_prompt}

Normalized corpus:
{normalized_corpus}

Return a short internal acknowledgment that the corpus is ready for analysis.
"""


def build_ingestion_agent(settings: Settings) -> LlmAgent:
    return LlmAgent(
        name="ingestion_agent",
        description="Represents the deterministic ingestion stage inside the agent graph.",
        model=settings.default_model,
        instruction=INGESTION_INSTRUCTION,
    )
