"""House style: learning a profile, layout, report rendering, the style editor's number guard,
the synthesis prompt, and the CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import SystemMessage
from typer.testing import CliRunner

from cre_monitor import cli
from cre_monitor.config import get_settings
from cre_monitor.schemas import SkillFinding
from cre_monitor.style.editor import StyledTopic, StyledTopics, apply_style, guard_ok, numbers_in
from cre_monitor.style.profile import (
    DEFAULT_LAYOUT, LayoutSection, StyleProfile, learn_profile, load_profile, read_example, resolve_layout,
    save_profile,
)
from tests.test_graph import fake_llm  # noqa: F401  (pytest fixture)

EXAMPLE_A = """# London Offices Quarterly

## Key themes
- Take-up reached 2.6m sq ft in Q2 2026, 6% above the long-term average.
- Prime yields held at 5.25%, while gilts rose 48 bps.

## Leasing market
We expect demand to stay firm. Prime rents rose to £190 psf in the West End, up 8% year on year.

## Outlook
Supply remains tight into 2027.

## Sources
Agency research.
"""

EXAMPLE_B = """# Central London Market Watch

## Key themes
- Vacancy fell to 6.3% in Q2 2026.
- Under offer space rose quarter on quarter.

## Leasing market
Grade A take-up dominated. We see AI occupiers driving demand.

## Outlook
Rates are the key risk for values.
"""


@pytest.fixture
def examples(tmp_path) -> Path:
    folder = get_settings().style_dir / "reports"
    folder.mkdir(parents=True)
    (folder / "a.md").write_text(EXAMPLE_A, encoding="utf-8")
    (folder / "b.md").write_text(EXAMPLE_B, encoding="utf-8")
    (folder / "README.md").write_text("instructions - must be ignored", encoding="utf-8")
    return folder


# --------------------------------------------------------------------------- learning

def test_heuristic_learning_captures_layout_conventions_and_techniques(examples):
    profile = learn_profile()                                   # demo mode -> heuristic
    assert profile.method == "heuristic" and profile.sources == ["a.md", "b.md"]   # README skipped
    layout = [(s.section, s.title) for s in profile.layout]
    assert ("summary", "Key themes") in layout and ("watch_list", "Outlook") in layout
    assert [s for s, _ in layout].index("summary") < [s for s, _ in layout].index("watch_list")
    assert "psf" in profile.number_style and "basis points" in profile.number_style
    assert any("long-term average" in t.lower() for t in profile.techniques)
    assert "we" in profile.voice                                # first person plural detected
    # Saved for reuse and review.
    assert load_profile() == profile
    assert (get_settings().style_dir / "profile.md").read_text(encoding="utf-8").startswith("# House style")


def test_learning_with_llm_uses_bounded_excerpts(examples, fake_llm):  # noqa: F811
    fake_llm.structured["StyleProfile"] = StyleProfile(name="Agency house style", voice="crisp, third person")
    profile = learn_profile(use_llm=True)
    assert profile.method == "llm" and profile.name == "Agency house style"
    assert profile.sources == ["a.md", "b.md"] and profile.learned_at
    sent = str(fake_llm.calls[-1][-1].content)
    assert "=== REPORT: a.md ===" in sent and "Key themes" in sent


def test_no_examples_is_a_clear_error():
    with pytest.raises(ValueError, match="No example reports"):
        learn_profile()


def test_html_examples_are_read(tmp_path):
    page = tmp_path / "r.html"
    page.write_text("<html><body><article><h2>Key themes</h2><p>Prime rents rose to £190 psf in the "
                    "West End during the second quarter, supported by strong demand.</p></article></body></html>",
                    encoding="utf-8")
    assert "£190 psf" in read_example(page)


# --------------------------------------------------------------------------- layout

def test_resolve_layout_orders_retitles_and_never_drops_sections():
    assert resolve_layout(None) == DEFAULT_LAYOUT
    profile = StyleProfile(name="x", voice="v", layout=[
        LayoutSection(section="summary", title="Key themes"),
        LayoutSection(section="watch_list", title="Outlook"),
        LayoutSection(section="summary", title="duplicate ignored"),
    ])
    layout = resolve_layout(profile)
    assert layout[:2] == [("summary", "Key themes"), ("watch_list", "Outlook")]
    assert {s for s, _ in layout} == {s for s, _ in DEFAULT_LAYOUT}  # all sections still rendered
    assert dict(layout)["sources"] == "Sources"                       # default heading for omitted ones
    assert [s for s, _ in layout][-2:] == ["data_quality", "sources"]


def test_missing_sections_go_before_references_the_profile_placed():
    profile = StyleProfile(name="x", voice="v", layout=[
        LayoutSection(section="summary", title="At a glance"),
        LayoutSection(section="sources", title="References"),
    ])
    order = [s for s, _ in resolve_layout(profile)]
    assert order[0] == "summary" and order[-2:] == ["sources", "data_quality"]
    assert order.index("what_changed") < order.index("sources")       # not appended after References
    assert order.index("topics") < order.index("sources")


def test_brief_follows_house_layout_and_can_be_switched_off(examples, monkeypatch):
    from cre_monitor.graph.builder import run_brief

    learn_profile()
    html = Path(run_brief(["office-rents"])["report_paths"]["html"]).read_text(encoding="utf-8")
    md = Path(run_brief(["office-rents"])["report_paths"]["markdown"]).read_text(encoding="utf-8")
    assert "<h2>Key themes</h2>" in html and "<h2>Outlook</h2>" in html and "House style" in html
    assert html.index("<h2>Key themes</h2>") < html.index("<h2>Outlook</h2>") < html.index("<h2>Risks &amp; opportunities</h2>")
    assert "## Key themes" in md and "house style" in md.splitlines()[2]

    monkeypatch.setenv("REPORT_STYLE", "0")
    get_settings.cache_clear()
    plain = Path(run_brief(["office-rents"])["report_paths"]["html"]).read_text(encoding="utf-8")
    assert "<h2>Executive summary</h2>" in plain and "Key themes" not in plain


# --------------------------------------------------------------------------- style editor

def _finding(skill="office-rents", **kw):
    base = dict(skill=skill, headline="Prime rents hit £190 psf in Q2 2026.",
                summary="West End rents rose 8% year on year to £190 psf.", insights=["City at £95 psf."])
    return SkillFinding(**(base | kw))


def test_number_guard():
    f = _finding()
    assert numbers_in("2,600,000 and 3.750") == {"2600000", "3.75"}
    assert guard_ok(f, StyledTopic(skill=f.skill, headline="West End prime: £190 psf (Q2 2026)",
                                   summary="Up 8% y/y.", insights=["City: £95 psf."]))
    assert not guard_ok(f, StyledTopic(skill=f.skill, headline="Prime rents hit £195 psf",   # changed figure
                                       summary="Up 8%.", insights=[]))


def test_style_editor_restyles_but_guard_keeps_original_when_figures_change(fake_llm):  # noqa: F811
    good, bad = _finding("office-rents"), _finding("vacancy-availability")
    fake_llm.structured["StyledTopics"] = StyledTopics(topics=[
        StyledTopic(skill="office-rents", headline="West End prime: £190 psf (Q2 2026)",
                    summary="Rents up 8% y/y.", insights=["City: £95 psf."]),
        StyledTopic(skill="vacancy-availability", headline="Rents near £200 psf",            # invented figure
                    summary="Rising.", insights=[]),
    ])
    profile = StyleProfile(name="house", voice="crisp")
    failed = SkillFinding(skill="news-events", headline="h", summary="s", error="boom")
    out = {f.skill: f for f in apply_style([good, bad, failed], profile)}
    assert out["office-rents"].headline == "West End prime: £190 psf (Q2 2026)"          # restyled
    assert out["vacancy-availability"].headline == bad.headline                           # guard: original kept
    assert out["news-events"] == failed                                                   # failures untouched
    assert out["office-rents"].metrics == good.metrics                                    # facts untouched
    assert "HOUSE STYLE (house)" in fake_llm.calls[-1][0].content


def test_style_editor_failure_keeps_findings(fake_llm):  # noqa: F811
    findings = [_finding()]
    assert apply_style(findings, StyleProfile(name="h", voice="v")) == findings   # no StyledTopics scripted


def test_live_brief_puts_house_style_into_synthesis_prompt(fake_llm):  # noqa: F811
    from cre_monitor.graph.builder import run_brief

    save_profile(StyleProfile(name="Agency house style", voice="crisp, third person",
                              techniques=["Lead with the number"]))
    run_brief(["macro-economy"])
    synth_call = next(c for c, k in zip(fake_llm.calls, fake_llm.kinds) if k == "structured:ExecutiveSynthesis")
    system = synth_call[0].content
    assert isinstance(synth_call[0], SystemMessage) and "HOUSE STYLE (Agency house style)" in system
    assert "Lead with the number" in system and "facts and figures always take priority" in system


# --------------------------------------------------------------------------- CLI

def test_cli_style_learn_show_clear(examples):
    runner = CliRunner()
    learned = runner.invoke(cli.app, ["style", "learn", "--heuristic"])
    assert learned.exit_code == 0 and "Learned" in learned.output
    assert "Key themes" in runner.invoke(cli.app, ["style", "show"]).output
    assert "Profile removed" in runner.invoke(cli.app, ["style", "clear"]).output
    assert "No house style" in runner.invoke(cli.app, ["style", "show"]).output


def test_cli_brief_no_style(examples):
    learn_profile()
    result = CliRunner().invoke(cli.app, ["brief", "--skills", "office-rents", "--no-style"])
    assert result.exit_code == 0
    html = sorted(get_settings().reports_dir.rglob("brief_*.html"))[-1].read_text(encoding="utf-8")
    assert "<h2>Executive summary</h2>" in html and "Key themes" not in html
