"""Read offline fixture data from ``fixtures/``.

Fixtures make the agent testable and demoable without network access or
API keys. Layout::

    fixtures/
      search_results.json   # canned web_search hits, keyed by topic tag
      documents/            # canned page/PDF extracts for fetch_document
      news.json             # canned RSS items
      macro_series.json     # canned BoE / ONS / Nomis series
      findings/<skill>.json # complete SkillFinding per skill (demo mode)

Every fixture figure must carry a real source citation so that the demo
output is still traceable. Refresh them when new quarterly reports land
(see ``docs/SKILLS.md`` -> "Refreshing fixtures").
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from cre_monitor.config import get_settings


def fixtures_path(*parts: str) -> Path:
    """Absolute path inside the fixtures directory."""
    return get_settings().fixtures_dir.joinpath(*parts)


@lru_cache(maxsize=64)
def load_json(*parts: str) -> Any:
    """Load and cache a JSON fixture. Raises ``FileNotFoundError`` if absent."""
    with fixtures_path(*parts).open(encoding="utf-8") as fh:
        return json.load(fh)


def keyword_score(text: str, query: str) -> int:
    """Crude relevance score: number of query words found in ``text``.

    Good enough to pick the most relevant canned results for a query in
    offline mode; real relevance ranking is the search provider's job.
    """
    haystack = text.lower()
    return sum(1 for word in set(query.lower().split()) if len(word) > 2 and word in haystack)
