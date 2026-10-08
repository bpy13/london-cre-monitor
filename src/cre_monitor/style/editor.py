"""Style editor: rewrite each topic's text in the house style - without touching facts.

Runs in the report step (live mode only, when a style profile is active). One
LLM call restyles every successful finding's ``headline``, ``summary`` and
``insights``. A **number guard** protects the facts: a rewrite may not contain
any number that wasn't in the original text of that finding; if it does, that
finding keeps its original wording (and the reason is logged). Metrics,
citations, signals and confidence are never touched.
"""

from __future__ import annotations

import json
import logging
import re

from pydantic import BaseModel, Field

from cre_monitor.schemas import SkillFinding
from cre_monitor.style.profile import StyleProfile

logger = logging.getLogger(__name__)

EDITOR_PROMPT = """You are the editor of a London office market brief. Rewrite the text of each research topic
in the house style below. Rules:
- Keep the meaning and EVERY figure exactly as given (same numbers, periods, units and sources). Do not add new
  figures, dates or claims, and do not drop the key figures.
- Keep the same number of insights or fewer (merge where the style prefers fewer, never invent).
- Return every topic, identified by its `skill` value.

{style}"""


class StyledTopic(BaseModel):
    skill: str
    headline: str
    summary: str
    insights: list[str] = Field(default_factory=list)


class StyledTopics(BaseModel):
    topics: list[StyledTopic]


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_in(*texts: str) -> set[str]:
    """Normalised numbers in the texts ('2,600,000' -> '2600000', '3.750' -> '3.75')."""
    out = set()
    for t in texts:
        for n in _NUMBER.findall(t or ""):
            n = n.replace(",", "")
            if "." in n:
                n = n.rstrip("0").rstrip(".")
            out.add(n)
    return out


def guard_ok(original: SkillFinding, styled: StyledTopic) -> bool:
    """True if the rewrite introduces no number absent from the original finding text."""
    allowed = numbers_in(original.headline, original.summary, *original.insights)
    used = numbers_in(styled.headline, styled.summary, *styled.insights)
    return used <= allowed


def apply_style(findings: list[SkillFinding], profile: StyleProfile) -> list[SkillFinding]:
    """Restyle successful findings; failures and guard violations keep the original text.

    Never raises: any LLM problem returns the findings unchanged (styling is cosmetic).
    """
    targets = [f for f in findings if not f.error]
    if not targets:
        return findings
    from langchain_core.messages import HumanMessage, SystemMessage

    from cre_monitor.llm import STRUCTURED, get_llm

    payload = [{"skill": f.skill, "headline": f.headline, "summary": f.summary, "insights": f.insights}
               for f in targets]
    try:
        model = get_llm("skill").with_structured_output(StyledTopics, **STRUCTURED)
        result: StyledTopics = model.invoke([
            SystemMessage(EDITOR_PROMPT.format(style=profile.prompt_text())),
            HumanMessage(json.dumps(payload, ensure_ascii=False)),
        ])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Style editor failed (%s); keeping original wording", exc)
        return findings

    styled = {t.skill: t for t in result.topics}
    out = []
    for f in findings:
        s = styled.get(f.skill)
        if f.error or s is None:
            out.append(f)
        elif not guard_ok(f, s):
            logger.warning("Style editor changed figures for %s; keeping original wording", f.skill)
            out.append(f)
        else:
            out.append(f.model_copy(update={"headline": s.headline, "summary": s.summary,
                                            "insights": s.insights or f.insights}))
    return out
