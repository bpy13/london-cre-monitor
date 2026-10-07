"""Skill runner: execute ONE skill as a self-contained LangGraph sub-agent.

For each skill we compile a small ReAct-style subgraph::

    START -> agent --(tool calls & budget left)--> tools -> agent ...
                   \\--(done or budget exhausted)--> respond -> END

* ``agent``   - the skill-tier LLM, whose system prompt is the common
  research rules + the skill's SKILL.md body (progressive disclosure
  level 2), bound to *only* the tools the skill lists.
* ``tools``   - LangGraph's prebuilt ``ToolNode`` executing those tools.
* ``respond`` - a final structured-output call that converts the research
  transcript into a validated :class:`~cre_monitor.schemas.SkillFinding`.

Splitting research (free-form, tool-using) from the final structured answer
is deliberate: forcing JSON on every turn hurts tool use, while a dedicated
last step gives us reliable, schema-valid output.

In demo mode the subgraph is skipped and a fixture finding is returned.
Any exception becomes an *error finding* so one failing skill never aborts
the whole brief.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from functools import lru_cache
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from cre_monitor.config import get_settings
from cre_monitor.graph.state import SkillTask
from cre_monitor.llm import STRUCTURED, get_llm
from cre_monitor.schemas import METRIC_KEYS, SUBMARKETS, SkillFinding
from cre_monitor.skills import Skill, get_registry
from cre_monitor.tools import get_tools
from cre_monitor.tools.fixtures import load_json

logger = logging.getLogger(__name__)

#: Rules shared by every skill. Skill-specific methodology lives in SKILL.md.
COMMON_RULES = """You are a senior London commercial real estate research analyst working for
Nan Fung Group, a long-term investor and developer in London offices. Today is {today}.

Research rules (apply to every skill):
1. Use your tools. Never state a market figure you did not see in a tool result in this session.
2. Prefer the most recent quarter. Say which period each figure refers to.
3. Prefer primary sources (broker research PDFs, Bank of England, ONS) over news paraphrases.
   Verify key numbers with fetch_document when a search snippet is ambiguous.
4. Brokers define metrics differently (e.g. availability vs vacancy, take-up incl./excl. pre-lets).
   Record the source for every figure and keep conflicting figures as separate metrics - do not average.
5. Normalise submarket names to: {submarkets}.
6. Metric keys must come from: {metric_keys}.
7. Signals are from the perspective of a London office landlord/investor/developer.
8. Be concise. Stop researching once you have the evidence you need.

=== SKILL INSTRUCTIONS: {skill_name} ===
{instructions}
"""

RESPOND_PROMPT = """Research is complete. Convert your findings into the SkillFinding structure.
Only include metrics you actually found in tool results above, each with its source and URL.
Set confidence lower if sources are old, secondary or conflicting.
Task you were given: {question}"""


class SkillAgentState(TypedDict, total=False):
    """Private state of one skill sub-agent."""

    messages: Annotated[list[AnyMessage], add_messages]
    steps: int
    finding: SkillFinding


def build_system_prompt(skill: Skill) -> str:
    """Common rules + skill instructions, with today's date filled in."""
    return COMMON_RULES.format(
        today=date.today().isoformat(),
        submarkets=", ".join(SUBMARKETS),
        metric_keys=", ".join(METRIC_KEYS),
        skill_name=skill.name,
        instructions=skill.instructions,
    )


@lru_cache(maxsize=32)
def build_skill_agent(skill_name: str):
    """Compile (and cache) the sub-agent graph for ``skill_name``.

    Cached because compiling is cheap but not free, and the scheduled brief
    reuses the same skills on every run within a process.
    """
    skill = get_registry().get(skill_name)
    tools = get_tools(skill.meta.tools)
    llm = get_llm(skill.meta.model_tier)
    llm_with_tools = llm.bind_tools(tools)
    system = SystemMessage(build_system_prompt(skill))
    max_steps = get_settings().skill_max_steps

    def agent(state: SkillAgentState) -> dict:
        reply = llm_with_tools.invoke([system, *state["messages"]])
        return {"messages": [reply], "steps": state.get("steps", 0) + 1}

    def route(state: SkillAgentState) -> str:
        last = state["messages"][-1]
        wants_tools = isinstance(last, AIMessage) and bool(last.tool_calls)
        return "tools" if wants_tools and state.get("steps", 0) < max_steps else "respond"

    def respond(state: SkillAgentState) -> dict:
        msgs = list(state["messages"])
        # If we stopped because the step budget ran out, the last AI message
        # still contains unanswered tool calls; the Anthropic API rejects a
        # tool_use without a tool_result, so drop that message.
        if isinstance(msgs[-1], AIMessage) and msgs[-1].tool_calls:
            msgs = msgs[:-1]
        question = next((m.content for m in msgs if isinstance(m, HumanMessage)), "")
        structured = llm.with_structured_output(SkillFinding, **STRUCTURED)
        finding: SkillFinding = structured.invoke(
            [system, *msgs, HumanMessage(RESPOND_PROMPT.format(question=question))]
        )
        finding.skill = skill_name  # do not rely on the LLM for bookkeeping
        return {"finding": finding}

    g = StateGraph(SkillAgentState)
    g.add_node("agent", agent)
    g.add_node("tools", ToolNode(tools, handle_tool_errors=True))
    g.add_node("respond", respond)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", route, {"tools": "tools", "respond": "respond"})
    g.add_edge("tools", "agent")
    g.add_edge("respond", END)
    return g.compile(name=f"skill:{skill_name}")


def demo_finding(skill_name: str) -> SkillFinding:
    """Load the canned finding for ``skill_name`` from ``fixtures/findings``."""
    return SkillFinding.model_validate(load_json("findings", f"{skill_name}.json"))


def run_skill(skill_name: str, question: str) -> SkillFinding:
    """Run a skill end to end and return its finding (never raises).

    Args:
        skill_name: Registered skill name.
        question: Task for the skill (brief instruction or user question).
    """
    try:
        if get_settings().cre_demo_mode:
            return demo_finding(skill_name)
        agent = build_skill_agent(skill_name)
        # Each step = one LLM turn + one tool turn, plus the respond node.
        limit = 2 * get_settings().skill_max_steps + 5
        out = agent.invoke({"messages": [HumanMessage(question)]}, {"recursion_limit": limit})
        return out["finding"]
    except Exception as exc:  # noqa: BLE001 - isolate failures per skill
        logger.exception("Skill %s failed", skill_name)
        return SkillFinding(
            skill=skill_name,
            headline=f"{skill_name} could not be completed.",
            summary="The skill failed; see error.",
            confidence=0.0,
            error=f"{type(exc).__name__}: {exc}",
        )


def skill_runner(task: SkillTask) -> dict:
    """Graph node (invoked once per ``Send``). Appends one finding to state."""
    finding = run_skill(task["skill_name"], task["question"])
    logger.info(
        "Skill %s done: %d metrics, %d signals%s",
        finding.skill, len(finding.metrics), len(finding.signals),
        f" (ERROR {finding.error})" if finding.error else "",
    )
    return {"findings": [finding]}


def finding_to_json(f: SkillFinding) -> str:
    """Compact JSON of a finding, used when passing findings to other LLM prompts."""
    return json.dumps(f.model_dump(mode="json", exclude_none=True), ensure_ascii=False)
