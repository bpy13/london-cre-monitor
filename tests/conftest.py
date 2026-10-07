"""Shared pytest fixtures.

Every test runs fully offline and without API keys by default:

* ``CRE_OFFLINE=1`` -> tools read ``fixtures/``.
* ``CRE_DEMO_MODE=1`` -> no LLM (unless a test patches in a fake model).
* ``data_dir`` / ``reports_dir`` point at a per-test temp folder so tests
  never touch a developer's real metrics history or reports.

Tests marked ``@pytest.mark.live`` are skipped unless run with
``pytest -m live`` and real keys in ``.env``.
"""

from __future__ import annotations

import pytest

from cre_monitor.config import get_settings


def _clear_caches() -> None:
    """Reset every process-level cache that depends on settings."""
    from cre_monitor.graph.builder import get_chat_graph
    from cre_monitor.graph.nodes.skill_runner import build_skill_agent
    from cre_monitor.skills.registry import get_registry
    from cre_monitor.tools.fixtures import load_json

    for cached in (get_settings, get_registry, load_json, get_chat_graph, build_skill_agent):
        cached.cache_clear()


@pytest.fixture(autouse=True)
def offline_env(tmp_path, monkeypatch, request):
    """Isolated, offline, demo-mode settings for each test."""
    if request.node.get_closest_marker("live"):
        yield
        return
    monkeypatch.setenv("CRE_OFFLINE", "1")
    monkeypatch.setenv("CRE_DEMO_MODE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("TAVILY_API_KEY", "")
    monkeypatch.setenv("REPORT_PNG", "0")  # PNG export launches Chrome; one test opts back in
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    _clear_caches()
    yield
    _clear_caches()
