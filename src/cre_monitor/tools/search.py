"""``web_search`` tool: find broker research, deals and news on the web.

Provider cascade (first one available wins):

1. **Offline fixtures** when ``CRE_OFFLINE=1``.
2. **Tavily** when ``TAVILY_API_KEY`` is set - best quality: full-web search
   with domain filtering and page snippets (free tier: 1,000 credits/month).
3. **Google News RSS** - keyless fallback. Only covers news articles (not
   broker PDFs) but is good enough to keep the agent working without keys.

Each provider returns a list of :class:`SearchHit`; the LangChain tool wrapper
formats them as numbered text for the LLM.
"""

from __future__ import annotations

import logging
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

from langchain_core.tools import tool
from pydantic import BaseModel

from cre_monitor.config import get_settings
from cre_monitor.tools._http import http_get
from cre_monitor.tools.fixtures import keyword_score, load_json

logger = logging.getLogger(__name__)

#: Default domains for CRE research. Skills can pass a narrower list taken
#: from their own ``preferred_domains`` frontmatter.
DEFAULT_CRE_DOMAINS: list[str] = [
    "knightfrank.co.uk", "savills.co.uk", "cbre.co.uk", "jll.co.uk",
    "cushmanwakefield.com", "colliers.com", "avisonyoung.co.uk",
    "realestate.bnpparibas.co.uk", "estatesgazette.co.uk", "propertyweek.com",
    "react-news.com", "costar.com", "ft.com", "cityam.com",
]


class SearchHit(BaseModel):
    """A single search result, provider-independent."""

    title: str
    url: str
    snippet: str = ""
    published: str = ""  # ISO date where known
    source: str = ""


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------


def _search_fixtures(query: str, max_results: int) -> list[SearchHit]:
    """Rank canned hits by keyword overlap with the query."""
    hits = [SearchHit(**h) for h in load_json("search_results.json")]
    ranked = sorted(hits, key=lambda h: keyword_score(f"{h.title} {h.snippet}", query), reverse=True)
    return ranked[:max_results]


def _search_tavily(query: str, domains: list[str] | None, recency_days: int, max_results: int) -> list[SearchHit]:
    """Search via Tavily. Imported lazily so the package is optional at runtime."""
    from tavily import TavilyClient

    client = TavilyClient(api_key=get_settings().tavily_api_key)
    resp = client.search(
        query=query,
        search_depth="advanced",
        max_results=max_results,
        include_domains=domains or DEFAULT_CRE_DOMAINS,
        days=recency_days,
    )
    return [
        SearchHit(
            title=r.get("title", ""),
            url=r.get("url", ""),
            snippet=(r.get("content") or "")[:800],
            published=r.get("published_date") or "",
            source=r.get("url", "").split("/")[2] if r.get("url") else "",
        )
        for r in resp.get("results", [])
    ]


def _search_google_news(query: str, max_results: int) -> list[SearchHit]:
    """Keyless fallback: Google News RSS search, restricted to UK English."""
    import feedparser

    url = (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(query + ' when:90d')}&hl=en-GB&gl=GB&ceid=GB:en"
    )
    feed = feedparser.parse(http_get(url).text)
    hits: list[SearchHit] = []
    for entry in feed.entries[:max_results]:
        published = ""
        if entry.get("published"):
            try:
                published = parsedate_to_datetime(entry.published).date().isoformat()
            except (TypeError, ValueError):
                pass
        hits.append(
            SearchHit(
                title=entry.get("title", ""),
                url=entry.get("link", ""),
                snippet=entry.get("summary", "")[:400],
                published=published,
                source=entry.get("source", {}).get("title", "") if entry.get("source") else "",
            )
        )
    return hits


def search(
    query: str,
    domains: list[str] | None = None,
    recency_days: int = 180,
    max_results: int = 6,
) -> list[SearchHit]:
    """Run a web search through the first available provider.

    Args:
        query: Free-text query, e.g. ``"Knight Frank London office Q2 2026 take-up"``.
        domains: Restrict to these domains (Tavily only).
        recency_days: Only return results newer than this (Tavily only).
        max_results: Maximum number of hits.

    Returns:
        Up to ``max_results`` hits; empty list if every provider failed.
    """
    s = get_settings()
    if s.cre_offline:
        return _search_fixtures(query, max_results)
    if s.tavily_api_key:
        try:
            return _search_tavily(query, domains, recency_days, max_results)
        except Exception as exc:  # noqa: BLE001 - any provider error -> fall back
            logger.warning("Tavily search failed (%s); falling back to Google News", exc)
    try:
        return _search_google_news(query, max_results)
    except Exception as exc:  # noqa: BLE001
        logger.error("Google News search failed: %s", exc)
        return []


def format_hits(hits: list[SearchHit]) -> str:
    """Render hits as compact numbered text for the LLM."""
    if not hits:
        return "No results. Try a broader query or different keywords."
    lines = []
    for i, h in enumerate(hits, 1):
        meta = " | ".join(x for x in (h.source, h.published) if x)
        lines.append(f"[{i}] {h.title} ({meta})\nURL: {h.url}\n{h.snippet}".strip())
    return "\n\n".join(lines)


# --------------------------------------------------------------------------
# LangChain tool
# --------------------------------------------------------------------------


@tool
def web_search(query: str, domains: list[str] | None = None, recency_days: int = 180) -> str:
    """Search the web for London office market research, deals and news.

    Use specific queries that name the broker, metric and period, e.g.
    "Knight Frank London office take-up Q2 2026" or "City of London Grade A
    vacancy 2026". Follow up promising hits with fetch_document to read the
    full source before quoting numbers.

    Args:
        query: Search query.
        domains: Optional list of domains to restrict to (e.g. ["knightfrank.co.uk"]).
        recency_days: Only include results published in the last N days.
    """
    return format_hits(search(query, domains=domains, recency_days=recency_days))
