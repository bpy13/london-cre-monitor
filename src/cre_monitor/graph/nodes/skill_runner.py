"""Skill runner: execute ONE skill as a self-contained LangGraph sub-agent.

For each skill we compile a small ReAct-style subgraph::

    START -> agent --(research tool calls)--> tools --> agent ...
               |                                 \\--(step budget used)--> wrap_up --> agent
               |--(no tool call: answered in plain text)--> nudge --> agent
               \\--(calls submit_finding)--> finish --(invalid)--> agent
                                                  \\--(valid)--> END

* ``agent``  - the skill-tier LLM, whose system prompt is the common research
  rules + the skill's SKILL.md body (progressive disclosure level 2), bound to
  the skill's tools **plus** ``submit_finding``.
* ``tools``  - LangGraph's prebuilt ``ToolNode`` executing research tools.
* ``finish`` - validates the ``submit_finding`` arguments into a
  :class:`~cre_monitor.schemas.SkillFinding`. Validation errors go back to the
  agent as the tool result, so it can correct and resubmit.
* ``wrap_up`` / ``nudge`` - append a user message asking the agent to submit
  now (budget reached / it answered in plain text instead of submitting).

Why the final answer is a tool call (not a separate structured-output call):
current Claude models (Opus/Sonnet 5.5) think between tool calls, and each
thinking block is cryptographically bound to the conversation **including its
tool list**. Re-sending the transcript to a request with a different tool list
(e.g. a tools-less structured-output call) is rejected with HTTP 400 ("Invalid
signature in thinking block ... the tools list differs"). So every request in a
skill uses the *same* bound tools and the conversation is strictly append-only.

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

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field, ValidationError

from cre_monitor.config import get_settings
from cre_monitor.graph.state import SkillTask
from cre_monitor.llm import get_llm
from cre_monitor.schemas import METRIC_KEYS, SUBMARKETS, Citation, Metric, Signal, SkillFinding
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
9. Finish by calling the submit_finding tool exactly once with your structured result. Include only
   metrics you actually found in tool results, each with its source and URL; lower the confidence if
   sources are old, secondary or conflicting. Do not write the final result as plain text.

=== SKILL INSTRUCTIONS: {skill_name} ===
{instructions}
"""

#: Name of the tool the agent calls to deliver its result.
SUBMIT_TOOL = "submit_finding"
#: Appended (as a user message) when the research step budget is used up.
WRAP_UP_PROMPT = ("You have reached the research budget for this task. Call submit_finding now with what "
                  "you have found so far, lowering the confidence if the evidence is incomplete.")
#: Appended when the agent answered in plain text instead of calling submit_finding.
NUDGE_PROMPT = "Please deliver your result by calling the submit_finding tool (not as plain text)."
#: How many invalid submissions / reminders are tolerated before the skill fails.
MAX_SUBMIT_RETRIES = 2
MAX_NUDGES = 2


class FindingSubmission(BaseModel):
    """Arguments of ``submit_finding``: a SkillFinding without the bookkeeping
    fields (``skill``, ``error``) that the app fills in itself."""

    headline: str = Field(description="One-sentence takeaway for an executive.")
    summary: str = Field(description="2-5 sentence narrative of the evidence and trend.")
    metrics: list[Metric] = Field(default_factory=list)
    insights: list[str] = Field(default_factory=list, description="Bullet-point observations.")
    signals: list[Signal] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="0-1, given source quality and recency.")


#: Anthropic-format tool definition (passed through by LangChain's bind_tools).
SUBMIT_TOOL_DEF = {
    "name": SUBMIT_TOOL,
    "description": ("Submit your final research result for this task. Call this exactly once, when you "
                    "have the evidence you need (or when asked to wrap up)."),
    "input_schema": FindingSubmission.model_json_schema(),
}


class SkillAgentState(TypedDict, total=False):
    """Private state of one skill sub-agent."""

    messages: Annotated[list[AnyMessage], add_messages]
    steps: int            # agent (LLM) turns taken
    nudges: int           # reminders sent (plain-text answers / budget wrap-up)
    submit_errors: int    # invalid submit_finding attempts
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
    # ONE binding used for every request in this skill: the tool list must never
    # change mid-conversation, or the API rejects the earlier thinking blocks.
    llm_with_tools = llm.bind_tools([*tools, SUBMIT_TOOL_DEF])
    system = SystemMessage(build_system_prompt(skill))
    max_steps = get_settings().skill_max_steps

    def _submit_call(state: SkillAgentState) -> dict | None:
        last = state["messages"][-1]
        if isinstance(last, AIMessage):
            return next((c for c in last.tool_calls if c["name"] == SUBMIT_TOOL), None)
        return None

    def agent(state: SkillAgentState) -> dict:
        reply = llm_with_tools.invoke([system, *state["messages"]])
        return {"messages": [reply], "steps": state.get("steps", 0) + 1}

    def route_agent(state: SkillAgentState) -> str:
        if _submit_call(state):
            return "finish"
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"  # pending tool calls always get results (API requirement)
        if state.get("nudges", 0) >= MAX_NUDGES:
            raise RuntimeError("Agent did not submit a finding after repeated reminders")
        return "nudge"

    def route_tools(state: SkillAgentState) -> str:
        if state.get("steps", 0) >= max_steps:
            if state.get("nudges", 0) >= MAX_NUDGES:
                raise RuntimeError("Research budget exhausted without a submitted finding")
            return "wrap_up"
        return "agent"

    def wrap_up(state: SkillAgentState) -> dict:
        return {"messages": [HumanMessage(WRAP_UP_PROMPT)], "nudges": state.get("nudges", 0) + 1}

    def nudge(state: SkillAgentState) -> dict:
        return {"messages": [HumanMessage(NUDGE_PROMPT)], "nudges": state.get("nudges", 0) + 1}

    def finish(state: SkillAgentState) -> dict:
        call = _submit_call(state)
        try:
            submission = FindingSubmission.model_validate(call["args"])
        except ValidationError as exc:
            errors = state.get("submit_errors", 0) + 1
            if errors > MAX_SUBMIT_RETRIES:
                raise RuntimeError(f"submit_finding arguments invalid after {errors} attempts: {exc}") from exc
            # Report the problem as the tool's result - append-only, same tool list.
            msgs = [ToolMessage(f"Invalid submission, please fix and call {SUBMIT_TOOL} again:\n{exc}",
                                tool_call_id=call["id"], status="error")]
            # Every tool_use in that turn needs a tool_result, or the next request is rejected.
            for other in state["messages"][-1].tool_calls:
                if other["id"] != call["id"]:
                    msgs.append(ToolMessage(f"Not run: call {SUBMIT_TOOL} on its own, after any research.",
                                            tool_call_id=other["id"], status="error"))
            return {"messages": msgs, "submit_errors": errors}
        # skill/error are bookkeeping fields set by the app, never trusted from the LLM.
        return {"finding": SkillFinding(skill=skill_name, **submission.model_dump())}

    def route_finish(state: SkillAgentState) -> str:
        return END if state.get("finding") is not None else "agent"

    g = StateGraph(SkillAgentState)
    g.add_node("agent", agent)
    g.add_node("tools", ToolNode(tools, handle_tool_errors=True))
    g.add_node("wrap_up", wrap_up)
    g.add_node("nudge", nudge)
    g.add_node("finish", finish)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", route_agent, ["finish", "tools", "nudge"])
    g.add_conditional_edges("tools", route_tools, ["agent", "wrap_up"])
    g.add_edge("wrap_up", "agent")
    g.add_edge("nudge", "agent")
    g.add_conditional_edges("finish", route_finish, ["agent", END])
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
        # Each step = one LLM turn + one tool turn; headroom for reminders and resubmissions.
        limit = 2 * get_settings().skill_max_steps + 4 * (MAX_NUDGES + MAX_SUBMIT_RETRIES) + 5
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
