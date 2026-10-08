"""Sample data and builders shared by several test files (reports, answer-key entries, metrics)."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from cre_monitor.benchmark import answer_key as ak
from cre_monitor.benchmark.answer_key import AnswerKey, KeyEntry
from cre_monitor.config import get_settings
from cre_monitor.schemas import Metric, SkillFinding
from cre_monitor.skills.editor import SkillDraft
from tests.support.fake_llm import submit_call, tool_call


AY_URL = "https://www.avisonyoung.co.uk/central-london-office-analysis"   # an offline fixture document


REPORT = ("# Central London Office Market Update Q2 2026\n\nTake-up reached 2.6m sq ft in Q2 2026. "
          "Vacancy was unchanged at 6.3%. Prime rents in the West End rose to £190 psf. Source: " + AY_URL)


def key_entry(**kw) -> KeyEntry:
    base = dict(key="take_up_sqft", submarket="Central London", period="2026-Q2", value=2_600_000, unit="sq ft",
                source="Avison Young", citation=AY_URL, confidence=0.9)
    return KeyEntry(**(base | kw))


def agent_metric(**kw) -> Metric:
    base = dict(key="take_up_sqft", submarket="Central London", period="2026-Q2", value=2_600_000, unit="sq ft",
                source="Avison Young", url=AY_URL)
    return Metric(**(base | kw))


def run_key() -> AnswerKey:
    key = AnswerKey(report="ref.md", period="2026-Q2", publisher="Avison Young", themes=["Take-up steady"],
                    entries=[key_entry(status="accepted"),
                             key_entry(key="vacancy_rate", value=6.3, unit="%", status="accepted")])
    ak.compute_signals(key, REPORT)
    return key


def script_benchmark_skill(fake_llm, monkeypatch, tokens=(20_000, 2_000)):
    """One skill run: read the cited page, then submit 1 right and 1 invented figure."""
    monkeypatch.setenv("BENCHMARK_TARGET_USD", "0.01")
    get_settings.cache_clear()
    usage = {"input_tokens": tokens[0], "output_tokens": tokens[1], "total_tokens": sum(tokens)}
    finding = fake_llm.macro.model_copy(update={"metrics": [
        agent_metric(), agent_metric(key="vacancy_rate", value=9.9, unit="%")]})
    submit = submit_call(finding)
    submit.usage_metadata = usage
    fake_llm.responses[:] = [
        AIMessage("", tool_calls=[tool_call("fetch_document", {"url": AY_URL}, "c1")], usage_metadata=usage),
        submit]


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


def style_finding(skill="office-rents", **kw):
    base = dict(skill=skill, headline="Prime rents hit £190 psf in Q2 2026.",
                summary="West End rents rose 8% year on year to £190 psf.", insights=["City at £95 psf."])
    return SkillFinding(**(base | kw))


SKILL_INSTRUCTIONS = ("# Lease events\n\n## Goal\nTrack lease expiries and break options in central London.\n\n"
                      "## Method\nSearch broker reports and news for lease events.")


def skill_draft(**kw) -> SkillDraft:
    """A valid new-skill draft ('lease-events'); override any field with keyword arguments."""
    return SkillDraft(**({"name": "lease-events", "description": "Lease expiries and breaks across central London.",
                          "tools": ["web_search"], "metrics": [], "instructions": SKILL_INSTRUCTIONS} | kw))


REAL_403 = ("AnthropicPermissionDeniedError: Error code: 403 - "
            "{'error': {'type': 'forbidden', 'message': 'Request not allowed'}}")
