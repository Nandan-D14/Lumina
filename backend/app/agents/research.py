from __future__ import annotations

from google.adk.agents import LlmAgent

from ..config import Settings
from ..schemas.domain import ResearchBranch
from ..tools.fetch_url import fetch_url
from ..tools.google_search import google_search_tool
from ..tools.scrape_html import scrape_html


RESEARCH_INSTRUCTION = """
You are the research specialist for a document-intelligence system.
User prompt:
{user_prompt}

Allow web research: {allow_web_research}
Should run research: {should_run_research}
Allow scraping: {allow_scraping}
Normalized corpus:
{normalized_corpus}

Existing source citations:
{initial_citations_json}

Rules:
- If should_run_research is false, do not call any tools and return an empty research branch.
- If allow_web_research is true, search for current, authoritative public sources relevant to the user prompt.
- If allow_web_research is false but URL sources are already present in the normalized corpus, summarize only those grounded URL sources and do not use google_search.
- Prefer primary sources, official reports, regulators, and reputable publications.
- Use fetch_url and scrape_html to inspect at most 3 sources when helpful.
- Tool-created artifacts and citations are appended to session state automatically. Reflect them in your returned branch.
- Return a concise grounded summary, findings, citations, and artifact names only.
- Never include unsupported claims.
"""


def build_research_agent(settings: Settings) -> LlmAgent:
    return LlmAgent(
        name="research_agent",
        description="Finds current public information and cites authoritative sources.",
        model=settings.default_model,
        instruction=RESEARCH_INSTRUCTION,
        tools=[google_search_tool, fetch_url, scrape_html],
        output_schema=ResearchBranch,
        output_key="research_branch",
    )
