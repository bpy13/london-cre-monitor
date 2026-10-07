"""``fetch_document`` tool: read the full text of a web page or PDF.

Broker research (Knight Frank, CBRE, ...) is mostly published as PDF, so
this tool handles both HTML (via trafilatura's boilerplate removal) and PDF
(via pypdf). Long documents are trimmed: if the caller passes ``focus``
keywords we keep only the paragraphs mentioning them, which saves a large
number of tokens on 30-page reports.
"""

from __future__ import annotations

import io
import logging
import re

from langchain_core.tools import tool

from cre_monitor.config import get_settings
from cre_monitor.tools._http import http_get
from cre_monitor.tools.fixtures import fixtures_path, load_json

logger = logging.getLogger(__name__)

#: Hard cap on characters returned to the LLM (~3k tokens).
MAX_CHARS = 12_000


def _pdf_to_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def _html_to_text(html: str) -> str:
    import trafilatura

    return trafilatura.extract(html, include_tables=True, favor_recall=True) or ""


def extract_text(url: str) -> str:
    """Download ``url`` and return its plain text (HTML or PDF).

    In offline mode, looks the URL up in ``fixtures/documents/index.json``.

    Raises:
        KeyError: Offline and the URL has no fixture.
        httpx.HTTPError: Online and the download failed.
    """
    if get_settings().cre_offline:
        filename = load_json("documents", "index.json")[url]
        return fixtures_path("documents", filename).read_text(encoding="utf-8")

    resp = http_get(url, timeout=60)
    is_pdf = url.lower().endswith(".pdf") or "pdf" in resp.headers.get("content-type", "")
    return _pdf_to_text(resp.content) if is_pdf else _html_to_text(resp.text)


def focus_text(text: str, focus: str | None, max_chars: int = MAX_CHARS) -> str:
    """Trim ``text`` to ``max_chars``, preferring paragraphs that mention ``focus``.

    Args:
        text: Full document text.
        focus: Space- or comma-separated keywords (case-insensitive). If
            ``None``/empty the document head is returned.
        max_chars: Output budget.
    """
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not focus:
        return text[:max_chars]
    words = [w for w in re.split(r"[,\s]+", focus.lower()) if len(w) > 2]
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    relevant = [p for p in paragraphs if any(w in p.lower() for w in words)]
    out = "\n\n".join(relevant or paragraphs)
    return out[:max_chars]


@tool
def fetch_document(url: str, focus: str | None = None) -> str:
    """Read the text of a web page or PDF report (e.g. a broker quarterly).

    Use after web_search to verify numbers in the original source. Pass
    `focus` keywords (e.g. "vacancy, availability, City") to receive only the
    relevant paragraphs of long reports.

    Args:
        url: Address of the page or PDF.
        focus: Optional keywords to filter paragraphs by.
    """
    try:
        text = extract_text(url)
    except KeyError:
        return f"No offline copy of {url}. Use a URL returned by web_search."
    except Exception as exc:  # noqa: BLE001 - surface any failure to the LLM
        logger.warning("fetch_document failed for %s: %s", url, exc)
        return f"Could not fetch {url}: {exc}. Try another source."
    if not text.strip():
        return f"{url} returned no extractable text (scanned PDF or JS-only page)."
    return f"SOURCE: {url}\n\n{focus_text(text, focus)}"
