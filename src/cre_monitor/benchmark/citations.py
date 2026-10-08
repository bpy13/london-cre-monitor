"""Citation check: does the page the agent cited actually contain the figure? (No LLM.)

For each metric with a URL, the page is fetched once with the same reader the
agent uses (``tools.documents.extract_text``: HTML via trafilatura, PDF via
pypdf) and searched for the value with :func:`~cre_monitor.benchmark.scoring.value_in_text`.

Statuses:

* ``contains``     - page opened and the value is in it.
* ``missing``      - page opened, value not found (wrong number, wrong page, or the
                     figure is in a chart image).
* ``unverifiable`` - page could not be read: blocked (403), paywalled, timed out,
                     or (offline mode) not in the fixtures. Not counted as a failure.
* ``no_url``       - the figure had no citation link (the validator already warns).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from cre_monitor.benchmark.scoring import value_in_text
from cre_monitor.schemas import Metric

logger = logging.getLogger(__name__)


@dataclass
class CitationResult:
    key: str
    submarket: str
    value: float
    url: str
    status: str  # contains | missing | unverifiable | no_url
    detail: str = ""


@dataclass
class CitationScore:
    """Percentages (0-100, None when undefined)."""

    checked: int = 0
    opened: int = 0
    contains: int = 0
    unverifiable: int = 0
    no_url: int = 0
    pct_opened: float | None = None      # of figures with a URL
    pct_contains: float | None = None    # of pages that opened


def check_citations(metrics: list[Metric]) -> tuple[CitationScore, list[CitationResult]]:
    """Check every metric's URL (each page fetched once)."""
    from cre_monitor.tools.documents import extract_text

    pages: dict[str, str | None] = {}
    errors: dict[str, str] = {}
    results = []
    for m in metrics:
        if not m.url:
            results.append(CitationResult(m.key, m.submarket, m.value, "", "no_url"))
            continue
        if m.url not in pages:
            try:
                pages[m.url] = extract_text(m.url)
            except Exception as exc:  # noqa: BLE001 - any failure to read = unverifiable, not a crash
                pages[m.url] = None
                errors[m.url] = f"{type(exc).__name__}: {exc}"[:200]
        text = pages[m.url]
        if text is None or not text.strip():
            results.append(CitationResult(m.key, m.submarket, m.value, m.url, "unverifiable",
                                          errors.get(m.url, "empty page")))
        else:
            status = "contains" if value_in_text(m.value, text) else "missing"
            results.append(CitationResult(m.key, m.submarket, m.value, m.url, status))

    with_url = [r for r in results if r.status != "no_url"]
    opened = [r for r in with_url if r.status != "unverifiable"]
    contains = [r for r in opened if r.status == "contains"]
    pct = lambda n, d: round(100 * n / d, 1) if d else None  # noqa: E731
    score = CitationScore(checked=len(results), opened=len(opened), contains=len(contains),
                          unverifiable=len(with_url) - len(opened), no_url=len(results) - len(with_url),
                          pct_opened=pct(len(opened), len(with_url)), pct_contains=pct(len(contains), len(opened)))
    return score, results
