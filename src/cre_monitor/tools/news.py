"""``rss_news`` tool: latest headlines from curated RSS feeds.

Feeds were chosen because they are free, keyless and verified to work
(October 2026). Add or remove feeds in :data:`FEEDS`; the key is what the
LLM passes as ``feed``. CoStar and Property Week were tested and rejected
(403 / empty feed).
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

FEEDS: dict[str, str] = {
    # Trade press: deals, developments, occupier moves.
    "estates_gazette": "https://www.estatesgazette.co.uk/feed/",
    # Monetary policy announcements, speeches, MPC minutes.
    "bank_of_england": "https://www.bankofengland.co.uk/rss/news",
    # Upcoming official statistics releases (for the "watch list").
    "ons_releases": "https://www.ons.gov.uk/releasecalendar?rss",
}

#: Google News search feed - the ``{q}`` placeholder is filled with ``query``.
GOOGLE_NEWS = "https://news.google.com/rss/search?q={q}&hl=en-GB&gl=GB&ceid=GB:en"


class NewsItem(BaseModel):
    """One headline."""

    title: str
    url: str
    published: str = ""
    feed: str = ""
    summary: str = ""


def _parse_feed(name: str, url: str, limit: int) -> list[NewsItem]:
    import feedparser

    parsed = feedparser.parse(http_get(url).text)
    items = []
    for e in parsed.entries[:limit]:
        published = ""
        if e.get("published"):
            try:
                published = parsedate_to_datetime(e.published).date().isoformat()
            except (TypeError, ValueError):
                published = e.published
        items.append(
            NewsItem(
                title=e.get("title", ""), url=e.get("link", ""), published=published,
                feed=name, summary=(e.get("summary") or "")[:300],
            )
        )
    return items


def get_news(feed: str = "google_news", query: str = "London office market", limit: int = 10) -> list[NewsItem]:
    """Fetch recent headlines.

    Args:
        feed: A key of :data:`FEEDS`, ``"google_news"`` (query-driven) or
            ``"all"`` (every curated feed, filtered by ``query``).
        query: Search terms (Google News) or keyword filter (other feeds).
        limit: Maximum items to return.
    """
    if get_settings().cre_offline:
        items = [NewsItem(**i) for i in load_json("news.json")]
        items.sort(key=lambda i: keyword_score(f"{i.title} {i.summary}", query), reverse=True)
        return items[:limit]

    if feed == "google_news":
        return _parse_feed("google_news", GOOGLE_NEWS.format(q=quote_plus(query + " when:30d")), limit)

    names = list(FEEDS) if feed == "all" else [feed]
    items: list[NewsItem] = []
    for name in names:
        if name not in FEEDS:
            raise ValueError(f"Unknown feed {name!r}. Options: {', '.join(FEEDS)}, google_news, all")
        try:
            items.extend(_parse_feed(name, FEEDS[name], 50))
        except Exception as exc:  # noqa: BLE001 - one broken feed shouldn't kill the rest
            logger.warning("Feed %s failed: %s", name, exc)
    if query:
        scored = [(keyword_score(f"{i.title} {i.summary}", query), i) for i in items]
        items = [i for score, i in sorted(scored, key=lambda t: t[0], reverse=True) if score > 0] or items
    return items[:limit]


@tool
def rss_news(feed: str = "google_news", query: str = "London office market", limit: int = 10) -> str:
    """Get recent headlines about the London property market and economy.

    Args:
        feed: "google_news" (searches all news with `query`), "estates_gazette",
            "bank_of_england", "ons_releases", or "all".
        query: Search terms or keyword filter, e.g. "City office letting".
        limit: Max number of headlines (default 10).
    """
    try:
        items = get_news(feed, query, limit)
    except Exception as exc:  # noqa: BLE001
        return f"News fetch failed: {exc}"
    if not items:
        return "No headlines found."
    return "\n".join(f"- [{i.published}] {i.title} ({i.feed}) {i.url}" for i in items)
