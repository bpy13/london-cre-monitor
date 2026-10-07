"""Data tools in offline mode (fixtures) plus pure helper functions."""

from __future__ import annotations

from cre_monitor.tools import TOOLS
from cre_monitor.tools.documents import focus_text
from cre_monitor.tools.fixtures import load_json


def test_web_search_offline_ranks_relevant_hits():
    out = TOOLS["web_search"].invoke({"query": "central London office vacancy rate"})
    assert out.startswith("[1]")
    assert "URL:" in out


def test_fetch_document_offline_returns_focused_text():
    url = next(iter(load_json("documents", "index.json")))
    out = TOOLS["fetch_document"].invoke({"url": url, "focus": "vacancy"})
    assert out.startswith(f"SOURCE: {url}")
    assert "vacancy" in out.lower()


def test_fetch_document_unknown_url_is_graceful():
    out = TOOLS["fetch_document"].invoke({"url": "https://nowhere.example/x.pdf"})
    assert "No offline copy" in out


def test_rss_news_offline():
    out = TOOLS["rss_news"].invoke({"feed": "google_news", "query": "City letting"})
    assert out.startswith("- [")


def test_macro_tools_offline():
    assert "Bank Rate" in TOOLS["boe_series"].invoke({"name": "bank_rate"})
    assert "CPIH" in TOOLS["ons_series"].invoke({"name": "cpih_yoy"})
    assert "London" in TOOLS["ons_series"].invoke({"name": "london_employment_rate"})
    assert "Unknown series" in TOOLS["boe_series"].invoke({"name": "nope"})


def test_metrics_history_tool_reads_store():
    from cre_monitor.store import get_store

    get_store().seed_from_fixture()
    out = TOOLS["metrics_history"].invoke({"key": "prime_rent", "submarket": "West End"})
    assert "West End" in out and "History of prime_rent" in out


def test_focus_text_prefers_matching_paragraphs():
    text = "Intro about nothing.\n\nVacancy fell to 8%.\n\nRents rose."
    assert focus_text(text, "vacancy") == "Vacancy fell to 8%."
    assert focus_text(text, None, max_chars=5) == "Intro"
