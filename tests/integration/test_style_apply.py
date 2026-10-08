"""House style applied by Claude: learning, style editor, synthesis prompt."""

from __future__ import annotations

from langchain_core.messages import SystemMessage

from cre_monitor.schemas import SkillFinding
from cre_monitor.style.editor import StyledTopic, StyledTopics, apply_style
from cre_monitor.style.profile import StyleProfile, learn_profile, save_profile
from tests.support.fake_llm import submit_call
from tests.support.samples import style_finding


def test_learning_with_llm_uses_bounded_excerpts(examples, fake_llm):
    fake_llm.structured["StyleProfile"] = StyleProfile(name="Agency house style", voice="crisp, third person")
    profile = learn_profile(use_llm=True)
    assert profile.method == "llm" and profile.name == "Agency house style"
    assert profile.sources == ["a.md", "b.md"] and profile.learned_at
    sent = str(fake_llm.calls[-1][-1].content)
    assert "=== REPORT: a.md ===" in sent and "Key themes" in sent


def test_style_editor_restyles_but_guard_keeps_original_when_figures_change(fake_llm):
    good, bad = style_finding("office-rents"), style_finding("vacancy-availability")
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


def test_style_editor_failure_keeps_findings(fake_llm):
    findings = [style_finding()]
    assert apply_style(findings, StyleProfile(name="h", voice="v")) == findings   # no StyledTopics scripted


def test_live_brief_puts_house_style_into_synthesis_prompt(fake_llm):
    from cre_monitor.graph.builder import run_brief

    save_profile(StyleProfile(name="Agency house style", voice="crisp, third person",
                              techniques=["Lead with the number"]))
    run_brief(["macro-economy"])
    synth_call = next(c for c, k in zip(fake_llm.calls, fake_llm.kinds) if k == "structured:ExecutiveSynthesis")
    system = synth_call[0].content
    assert isinstance(synth_call[0], SystemMessage) and "HOUSE STYLE (Agency house style)" in system
    assert "Lead with the number" in system and "facts and figures always take priority" in system

    # Switched off for one run: no style in the prompt (the skill submits straight away this time).
    fake_llm.calls.clear()
    fake_llm.kinds.clear()
    fake_llm.responses[:] = [submit_call(fake_llm.macro)]
    run_brief(["macro-economy"], use_style=False)
    synth_call = next(c for c, k in zip(fake_llm.calls, fake_llm.kinds) if k == "structured:ExecutiveSynthesis")
    assert "HOUSE STYLE" not in synth_call[0].content
