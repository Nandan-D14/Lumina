def google_search_tool(query: str) -> str:
    """Perform a web search for the given query and return a summary of the top results."""
    try:
        from ddgs import DDGS
    except Exception:
        return "Search failed: optional dependency ddgs is not installed."

    ddgs = DDGS()
    try:
        results = ddgs.text(query, max_results=5)
        return str(results)
    except Exception as e:
        return f"Search failed: {str(e)}"
