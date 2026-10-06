"""Web search tool for the Researcher: Tavily (real) or a mock. Results are compacted to save tokens."""
from __future__ import annotations

import httpx

from app.config import Settings

WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for competitors, audience pain points and keywords for a product idea.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Concise search query"}},
            "required": ["query"],
        },
    },
}


def compact(results: list[dict], limit: int = 5, snippet_chars: int = 300) -> list[dict]:
    return [
        {"title": (r.get("title") or "")[:120], "url": r.get("url", ""), "snippet": (r.get("content") or r.get("snippet") or "")[:snippet_chars]}
        for r in results[:limit]
    ]


class MockSearch:
    async def search(self, query: str) -> list[dict]:
        return compact([
            {"title": "Market overview", "url": "https://example.com/market", "content": f"Overview for: {query}. Users complain existing tools are generic and take too long to set up."},
            {"title": "Top alternatives compared", "url": "https://example.com/alternatives", "content": "Popular alternatives are feature-heavy and not tailored to niche routines."},
        ])


class TavilySearch:
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def search(self, query: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                "https://api.tavily.com/search",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"query": query, "max_results": 5, "search_depth": "basic"},
            )
            r.raise_for_status()
            return compact(r.json().get("results", []))


def get_search_tool(settings: Settings):
    return MockSearch() if settings.mock_llm or not settings.tavily_api_key else TavilySearch(settings.tavily_api_key)
