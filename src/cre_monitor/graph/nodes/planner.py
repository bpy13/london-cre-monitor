"""Planner node: decide which skills to run, then fan out with ``Send``.

* **brief mode** - run every skill with ``in_brief: true`` (or the explicit
  ``skills_override`` from the CLI). No LLM needed.
* **chat mode** - the cheap *router* model reads only the skills' names and
  descriptions (progressive disclosure level 1) and picks the relevant ones.
  If the router is unavailable (demo mode) or fails, we fall back to the
  ``keywords`` declared in each SKILL.md.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import Send

from cre_monitor.config import get_settings
from cre_monitor.graph.state import AgentState, Replace, SkillTask
from cre_monitor.llm import STRUCTURED, get_llm
from cre_monitor.schemas import SkillSelection
from cre_monitor.skills import get_registry

logger = logging.getLogger(__name__)

BRIEF_TASK = (
    "Produce the latest-quarter picture for the scheduled London office market brief. "
    "Cover every metric listed for this skill, for Central London and each major submarket where available."
)

ROUTER_PROMPT = """You route questions about the London commercial real estate (office) market
to research skills. Pick the MINIMUM set of skills needed to answer well (usually 1-3).
If the question is small talk or can be answered purely from the earlier conversation,
return an empty list.

Available skills:
{catalog}"""


def last_question(state: AgentState) -> str:
    """Text of the most recent human message ('' if none)."""
    for msg in reversed(state.get("messages") or []):
        if isinstance(msg, HumanMessage) or getattr(msg, "type", "") == "human":
            return str(msg.content)
    return ""


def keyword_route(question: str) -> list[str]:
    """Fallback router: skills whose ``keywords`` occur in the question.

    Returns every research skill if nothing matches, so the user still gets
    a (broad) answer rather than nothing.
    """
    q = question.lower()
    registry = get_registry()

    def mentions(keyword: str) -> bool:
        # Whole-word match, so "rent" does not fire on "current".
        return re.search(rf"\b{re.escape(keyword)}\b", q) is not None

    hits = [s.name for s in registry.research_skills() if any(mentions(k) for k in s.meta.keywords)]
    return hits or [s.name for s in registry.research_skills()]


def llm_route(question: str) -> SkillSelection:
    """Ask the router LLM which skills to use (structured output)."""
    registry = get_registry()
    router = get_llm("router").with_structured_output(SkillSelection, **STRUCTURED)
    result: SkillSelection = router.invoke(
        [SystemMessage(ROUTER_PROMPT.format(catalog=registry.planner_catalog())), HumanMessage(question)]
    )
    # Never trust the LLM to spell names right - drop anything unknown.
    result.skills = [s for s in result.skills if s in registry and registry.get(s).meta.tools]
    return result


def planner(state: AgentState) -> dict:
    """Graph node. Chooses skills and resets per-run state."""
    registry = get_registry()
    mode = state.get("mode", "chat")
    override = state.get("skills_override")

    if override:
        unknown = [s for s in override if s not in registry]
        if unknown:
            raise ValueError(f"Unknown skills {unknown}. Available: {registry.names()}")
        selected, reasoning = list(override), "Skills specified explicitly by the caller."
    elif mode == "brief":
        selected = [s.name for s in registry.brief_skills()]
        reasoning = "Full scheduled brief: running every brief skill."
    else:
        question = last_question(state)
        if get_settings().cre_demo_mode:
            selected, reasoning = keyword_route(question), "Demo mode: keyword routing."
        else:
            try:
                sel = llm_route(question)
                selected, reasoning = sel.skills, sel.reasoning
            except Exception as exc:  # noqa: BLE001 - routing must never kill a chat turn
                logger.warning("LLM routing failed (%s); using keyword routing", exc)
                selected, reasoning = keyword_route(question), "Router failed; keyword routing used."

    run_id = f"{datetime.now():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    logger.info("Run %s (%s): skills=%s", run_id, mode, selected)
    return {
        "run_id": run_id,
        "selected_skills": selected,
        "planner_reasoning": reasoning,
        # Reset per-run outputs (state persists across chat turns).
        "findings": Replace([]),
        "validation_issues": [],
        "deltas": [],
        "synthesis": None,
        "answer": "",
    }


def fan_out(state: AgentState) -> list[Send] | str:
    """Conditional edge after the planner.

    Returns one ``Send`` per selected skill so they run **in parallel**, or
    jumps straight to ``chat_answer`` when no research is needed.
    """
    selected = state.get("selected_skills") or []
    if not selected:
        return "chat_answer"
    mode = state.get("mode", "chat")
    question = BRIEF_TASK if mode == "brief" else last_question(state)
    return [
        Send("skill_runner", SkillTask(skill_name=name, mode=mode, question=question))
        for name in selected
    ]
