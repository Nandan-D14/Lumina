from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.tools import AgentTool

from ..agents.table_reasoner import build_table_reasoner_agent
from ..config import Settings
from ..schemas.domain import VisualizationsBranch


VISUALIZATION_INSTRUCTION = """
You are the visualization planner.
User prompt:
{user_prompt}

Normalized corpus:
{normalized_corpus}

Available structured tables:
{normalized_tables_json}

Research context:
{research_branch?}

Constraints:
- Return at most {max_visualizations} visualizations.
- Prefer returning at least 4 visualizations when sufficient data exists.
- Use line charts for ordered or time-series comparisons.
- Use pie charts only for small, clear part-to-whole datasets.
- Use bar charts for category comparisons.
- Use table visualizations when narrative or mixed data is better shown in tabular form.
- Only include labels and numeric values when they are grounded.
- Ensure chart titles and reasons are explanatory, not generic.
- If the normalized tables are helpful, call the table_reasoner_agent tool and adapt its output to the final visualization list.
"""


def build_visualization_agent(settings: Settings) -> LlmAgent:
    table_reasoner_tool = AgentTool(build_table_reasoner_agent(settings), skip_summarization=True)
    return LlmAgent(
        name="visualization_agent",
        description="Plans grounded visualizations from structured and unstructured inputs.",
        model=settings.default_model,
        instruction=VISUALIZATION_INSTRUCTION,
        tools=[table_reasoner_tool],
        output_schema=VisualizationsBranch,
        output_key="visualizations_branch",
    )
