from __future__ import annotations

from google.adk.agents import LlmAgent

from ..config import Settings
from ..schemas.domain import VisualizationsBranch


TABLE_REASONER_INSTRUCTION = """
You are a table reasoning specialist that converts grounded tabular inputs into visualization candidates.

User prompt:
{user_prompt}

Normalized tables:
{normalized_tables_json}

Rules:
- Use only the provided tables.
- Propose visualization candidates only when labels and numeric values are explicitly grounded.
- Prefer line charts for time-series or ordered progression.
- Prefer bar charts for comparison across categories.
- Prefer pie charts only for small part-to-whole datasets.
- If no chart is reliable, return an empty visualization list.
"""


def build_table_reasoner_agent(settings: Settings) -> LlmAgent:
    return LlmAgent(
        name="table_reasoner_agent",
        description="Creates grounded visualization candidates from normalized tables.",
        model=settings.default_model,
        instruction=TABLE_REASONER_INSTRUCTION,
        output_schema=VisualizationsBranch,
    )
