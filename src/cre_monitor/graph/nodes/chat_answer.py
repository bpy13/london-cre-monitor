"""Chat answer node: reply to the user's question from the skill findings.

The answer is appended to ``messages`` so the checkpointer remembers the
conversation (follow-ups like "and how does that compare to the City?"
work within the same ``thread_id``).
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, SystemMessage

from cre_monitor.config import get_settings
from cre_monitor.graph.nodes.skill_runner import finding_to_json
from cre_monitor.graph.state import AgentState
from cre_monitor.llm import get_llm
from cre_monitor.schemas import Citation, MetricDelta, SkillFinding, ValidationIssue

logger = logging.getLogger(__name__)

ANSWER_PROMPT = """You are a London office market analyst answering a colleague at Nan Fung Group.
Answer the latest question using ONLY the research findings below and the conversation so far.

Style:
- Lead with the direct answer (numbers first, with period and source).
- Then 2-5 bullets of supporting evidence / context / implications for an investor-developer.
- Cite sources inline as [Publisher](url).
- If sources conflict or data quality issues exist, say so briefly.
- If the findings do not answer the question, say what is missing - never invent figures.

RESEARCH FINDINGS (JSON, one per skill):
{findings}

CHANGES VS EARLIER PERIODS:
{deltas}

DATA QUALITY ISSUES:
{issues}"""


def _citations(findings: list[SkillFinding]) -> list[Citation]:
    seen: dict[str, Citation] = {}
    for f in findings:
        for c in f.citations:
            seen.setdefault(c.url or c.title, c)
    return list(seen.values())


def rule_based_answer(findings: list[SkillFinding], deltas: list[MetricDelta], issues: list[ValidationIssue]) -> str:
    """Demo-mode answer: a structured digest of the relevant findings."""
    if not findings:
        return "I don't have research for that yet - try asking about rents, vacancy, take-up, supply, submarkets, macro, occupier demand or news."
    # Blocks are joined with blank lines so Markdown does not glue a paragraph
    # onto the preceding bullet list.
    blocks = ["*(Demo mode - answer assembled from canned research without an LLM.)*"]
    for f in findings:
        if f.error:
            blocks.append(f"**{f.skill}** - failed: {f.error}")
            continue
        bullets = "\n".join(
            f"- {m.submarket} {m.key.replace('_', ' ')}: {m.value:,.4g} {m.unit} ({m.period}, {m.source})"
            for m in f.metrics[:6]
        )
        blocks.append(f"**{f.headline}**\n\n{f.summary}" + (f"\n\n{bullets}" if bullets else ""))
    material = [d for d in deltas if d.is_material]
    if material:
        blocks.append("**What changed**\n\n" + "\n".join(f"- {d.describe()}" for d in material[:5]))
    cites = _citations(findings)
    if cites:
        blocks.append("**Sources**\n\n" + "\n".join(f"- [{c.publisher or c.title}]({c.url})" for c in cites[:8]))
    return "\n\n".join(blocks)


def chat_answer(state: AgentState) -> dict:
    """Graph node."""
    findings = state.get("findings") or []
    deltas = state.get("deltas") or []
    issues = state.get("validation_issues") or []

    if get_settings().cre_demo_mode:
        answer = rule_based_answer(findings, deltas, issues)
    else:
        system = ANSWER_PROMPT.format(
            findings="\n".join(finding_to_json(f) for f in findings) or "(none - answer from conversation)",
            deltas="\n".join(d.describe() for d in deltas if d.is_material) or "(none)",
            issues="\n".join(f"- {i.message}" for i in issues) or "(none)",
        )
        try:
            reply = get_llm("synthesis").invoke([SystemMessage(system), *state.get("messages", [])])
            answer = reply.content if isinstance(reply.content, str) else "".join(
                b.get("text", "") for b in reply.content if isinstance(b, dict)
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Chat answer LLM failed; returning digest")
            answer = rule_based_answer(findings, deltas, issues) + f"\n\n_(LLM error: {exc})_"
    return {"answer": answer, "messages": [AIMessage(answer)]}
