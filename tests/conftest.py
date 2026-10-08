"""Shared pytest configuration for every test.

Layout - one folder per test type, each automatically tagged with a marker of the same name
(so ``pytest tests/unit`` and ``pytest -m unit`` are equivalent):

===============  ==============================================================
``unit/``        one module in isolation (pure functions, its own temp files)
``integration/`` several components together (fake-LLM agent loops, stores, CLI)
``e2e/``         whole-pipeline journeys (a brief or chat turn, start to finish)
``ui/``          the Streamlit app via AppTest
``regression/``  reproductions of bugs that were fixed
``live/``        real external APIs (deselected by default; ``pytest -m live``)
``support/``     shared test code: fake LLM, fixtures, sample data (not tests)
===============  ==============================================================

Shared fixtures (``fake_llm``, ``examples``, ``api_refuses``) live in
``tests/support/fixtures.py`` and are loaded for every test via ``pytest_plugins``.

Every test runs fully offline and without API keys by default:

* ``CRE_OFFLINE=1`` -> tools read ``fixtures/``.
* ``CRE_DEMO_MODE=1`` -> no LLM (unless a test patches in a fake model).
* ``data_dir`` / ``reports_dir`` point at a per-test temp folder so tests
  never touch a developer's real metrics history or reports.
* ``skills/`` and ``catalog/`` are copied to the temp folder, so tests that
  edit skills or the catalogue never change the repo's files.

Tests marked ``@pytest.mark.live`` are skipped unless run with
``pytest -m live`` and real keys in ``.env``.
"""

from __future__ import annotations

import shutil

import pytest

from cre_monitor.config import PROJECT_ROOT, get_settings

#: Fixtures shared across folders (fake_llm, examples, api_refuses).
pytest_plugins = ["tests.support.fixtures"]

#: Folder -> marker. Every test is tagged with the marker of the folder it lives in.
TEST_TYPES = ("unit", "integration", "e2e", "ui", "regression", "live")


def pytest_collection_modifyitems(config, items):
    """Tag each test with its folder's marker, e.g. tests/unit/... -> @pytest.mark.unit."""
    for item in items:
        folder = item.path.parent.name
        if folder in TEST_TYPES:
            item.add_marker(getattr(pytest.mark, folder))


def _clear_caches() -> None:
    """Reset every process-level cache that depends on settings."""
    from cre_monitor.catalog import get_catalog
    from cre_monitor.graph.builder import get_chat_graph
    from cre_monitor.graph.nodes.skill_runner import build_skill_agent
    from cre_monitor.skills.registry import get_registry
    from cre_monitor.tools.fixtures import load_json

    for cached in (get_settings, get_registry, load_json, get_chat_graph, build_skill_agent, get_catalog):
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
    monkeypatch.setenv("EXPORTS_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("STYLE_DIR", str(tmp_path / "style"))      # never use the repo's style profile
    # Skills and the catalogue are editable from the UI: tests work on copies so they
    # can never modify the repo's files (copying ~10 small files per test is cheap).
    shutil.copytree(PROJECT_ROOT / "skills", tmp_path / "skills", ignore=shutil.ignore_patterns(".history", ".trash"))
    shutil.copytree(PROJECT_ROOT / "catalog", tmp_path / "catalog", ignore=shutil.ignore_patterns(".history"))
    monkeypatch.setenv("SKILLS_DIR", str(tmp_path / "skills"))
    monkeypatch.setenv("CATALOG_DIR", str(tmp_path / "catalog"))
    # Safety net: if a test ever builds a real Claude client by mistake, it fails instantly
    # (connection refused) instead of calling the real API.
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9")
    _clear_caches()
    yield
    _clear_caches()
