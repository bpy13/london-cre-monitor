"""Live smoke tests against real APIs (run with `pytest -m live`, needs keys)."""

from __future__ import annotations

import os

import pytest

from cre_monitor.config import get_settings


pytestmark = pytest.mark.live


@pytest.fixture(autouse=True)
def online(monkeypatch):
    monkeypatch.setenv("CRE_OFFLINE", "0")
    get_settings.cache_clear()
    from cre_monitor.tools.fixtures import load_json

    load_json.cache_clear()
    yield
    get_settings.cache_clear()


def test_boe_bank_rate_live():
    from cre_monitor.tools.macro import fetch_boe

    s = fetch_boe("bank_rate", months=3)
    assert s.latest is not None and 0 <= s.latest.value <= 15


@pytest.mark.parametrize("name", ["cpih_yoy", "unemployment_rate", "gdp_growth_qoq"])
def test_ons_series_live(name):
    from cre_monitor.tools.macro import fetch_ons

    assert fetch_ons(name).latest is not None


def test_nomis_london_employment_live():
    from cre_monitor.tools.macro import fetch_london_employment

    assert fetch_london_employment().latest.value > 50


def test_news_and_search_live():
    from cre_monitor.tools.news import get_news
    from cre_monitor.tools.search import search

    assert get_news("google_news", "London office market", 5)
    assert search("London office take-up 2026", max_results=3)


@pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY")
def test_skill_live_macro():
    os.environ["CRE_DEMO_MODE"] = "0"
    get_settings.cache_clear()
    from cre_monitor.graph.nodes.skill_runner import run_skill

    finding = run_skill("macro-economy", "What is the current Bank Rate and CPIH inflation?")
    assert finding.error is None, finding.error
    assert any(m.key == "bank_rate" for m in finding.metrics)
