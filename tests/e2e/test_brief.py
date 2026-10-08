"""Full brief runs (demo mode / failing API): report files, sections, deltas, incidents, house layout."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from cre_monitor.config import get_settings
from cre_monitor.graph.builder import build_graph, run_brief
from cre_monitor.style.profile import learn_profile


REAL_400 = ("AnthropicInvalidRequestError: Error code: 400 - {'type': 'error', 'error': {'type': "
            "'invalid_request_error', 'message': 'messages.1.content.4: Invalid `signature` in `thinking` block.'}}")


def _report_texts(state):
    from pathlib import Path

    html = Path(state["report_paths"]["html"]).read_text(encoding="utf-8")
    md = Path(state["report_paths"]["markdown"]).read_text(encoding="utf-8")
    raw_json = Path(state["report_paths"]["json"]).read_text(encoding="utf-8")
    return html, md, raw_json


def test_report_shows_friendly_panel_for_partial_failure(monkeypatch):
    """One skill fails (the real live 400), the other succeeds -> amber panel, no raw text for readers."""
    from cre_monitor.graph.builder import run_brief

    # importlib: graph/nodes/__init__ re-exports a *function* named skill_runner, shadowing the module.
    sr = importlib.import_module("cre_monitor.graph.nodes.skill_runner")
    real_demo = sr.demo_finding

    def flaky_demo(name):
        if name == "office-rents":
            raise RuntimeError(REAL_400)
        return real_demo(name)

    monkeypatch.setattr(sr, "demo_finding", flaky_demo)
    state = run_brief(["office-rents", "macro-economy"])
    incident = state["incident"]
    assert incident.scope == "partial" and incident.category.code == "app_error"

    html, md, raw_json = _report_texts(state)
    readable_html = html.split('<details class="tech">')[0]
    readable_md = md.split("## Technical details for engineers")[0]
    for readable in (readable_html, readable_md):
        assert "The app sent a request the AI service rejected" in readable   # plain-English title
        assert incident.id in readable                                       # same reference as CLI/UI
        assert "Not available this time" in readable                         # per-skill line
        assert "Error code" not in readable and "Skill failed:" not in readable   # no raw text for readers
    assert 'class="incident partial"' in html
    assert "the London engineering team" in readable_html                    # support contact
    assert "Error code: 400" in html.split('<details class="tech">')[1]      # raw kept for engineers ...
    assert "Error code: 400" in md.split("## Technical details for engineers")[1]
    assert "Skill failed:" in raw_json and incident.id in raw_json           # ... and in the audit JSON


def test_report_shows_red_panel_when_nothing_usable(api_refuses):
    from cre_monitor.graph.builder import run_brief

    state = run_brief(["macro-economy"])
    html, md, _ = _report_texts(state)
    assert 'class="incident total"' in html
    assert "This brief could not be produced from fresh research." in html
    assert "🚫" in md.split("## Executive summary")[0]


def test_brief_with_refused_api_reports_incident(api_refuses):
    from cre_monitor.graph.builder import run_brief

    state = run_brief(["macro-economy"])
    assert state["incident"].scope == "total"
    assert "synthesis" in state["incident"].affected
    # The report's watch list no longer carries the raw exception text.
    assert not any("Error code" in w for w in state["synthesis"].watch_list)


def test_brief_demo_end_to_end_writes_report(monkeypatch):
    monkeypatch.setenv("REPORT_PNG", "1")  # exercise the kaleido PNG path once
    get_settings.cache_clear()
    state = run_brief()
    findings = state["findings"]
    assert len(findings) == 8 and not any(f.error for f in findings)
    assert state["synthesis"].key_takeaways

    html = Path(state["report_paths"]["html"]).read_text(encoding="utf-8")
    md = Path(state["report_paths"]["markdown"]).read_text(encoding="utf-8")
    for section in ("Executive summary", "Risks &amp; opportunities", "Research by topic", "Sources"):
        assert section in html
    assert "plotly" in html.lower() and "chart-prime_rent_by_submarket" in html
    assert "## Executive summary" in md and "&amp;" not in md  # markdown must not be HTML-escaped
    pngs = list((Path(state["report_paths"]["html"]).parent / "charts" / state["run_id"]).glob("*.png"))
    assert pngs, "expected PNG charts (kaleido needs a local Chrome - run `plotly_get_chrome`)"
    assert f"](charts/{state['run_id']}/" in md


def test_first_brief_detects_changes_vs_seeded_history():
    state = run_brief()
    # Seed history ends one quarter before the fixture findings -> deltas exist.
    assert state["deltas"], "expected period-on-period changes vs seeded history"
    assert state["synthesis"].what_changed


def test_brief_skill_subset():
    state = run_brief(["office-rents", "macro-economy"])
    assert sorted(f.skill for f in state["findings"]) == ["macro-economy", "office-rents"]


def test_unknown_skill_override_raises():
    with pytest.raises(ValueError, match="Unknown skills"):
        build_graph().invoke({"mode": "brief", "messages": [], "skills_override": ["nope"]})


def test_brief_follows_house_layout_and_can_be_switched_off(examples, monkeypatch):
    from cre_monitor.graph.builder import run_brief

    learn_profile()
    html = Path(run_brief(["office-rents"])["report_paths"]["html"]).read_text(encoding="utf-8")
    md = Path(run_brief(["office-rents"])["report_paths"]["markdown"]).read_text(encoding="utf-8")
    assert "<h2>Key themes</h2>" in html and "<h2>Outlook</h2>" in html and "House style" in html
    assert html.index("<h2>Key themes</h2>") < html.index("<h2>Outlook</h2>") < html.index("<h2>Risks &amp; opportunities</h2>")
    assert "## Key themes" in md and "house style" in md.splitlines()[2]

    # Per run (CLI --no-style, UI toggle) ...
    plain = Path(run_brief(["office-rents"], use_style=False)["report_paths"]["html"]).read_text(encoding="utf-8")
    assert "<h2>Executive summary</h2>" in plain and "Key themes" not in plain
    # ... and globally (REPORT_STYLE=0 overrides use_style=True).
    monkeypatch.setenv("REPORT_STYLE", "0")
    get_settings.cache_clear()
    plain = Path(run_brief(["office-rents"])["report_paths"]["html"]).read_text(encoding="utf-8")
    assert "<h2>Executive summary</h2>" in plain and "Key themes" not in plain
