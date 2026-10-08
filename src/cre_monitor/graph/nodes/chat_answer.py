"""Chat answer node: reply to the user's question from the skill findings.

The answer is appended to ``messages`` so the checkpointer remembers the
conversation (follow-ups like "and how does that compare to the City?"
work within the same ``thread_id``).

If the user referenced earlier conversations, their context packs
(``reference_context``) are added to the prompt as clearly labelled, dated
*background*. Rules in the prompt make current research take precedence and
require the answer to say when it draws on an earlier conversation.
"""

from __future__ import annotations

import logging
import re

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
{issues}{references}"""

#: Appended to ANSWER_PROMPT only when the user referenced earlier conversations.
REFERENCES_PROMPT = """

EARLIER CONVERSATIONS THE USER REFERENCED (background - not current research):
{packs}

Rules for earlier conversations:
- Use them for continuity: what was asked before, what was concluded, how things compare.
- Current RESEARCH FINDINGS take precedence. If an earlier figure differs from a current one,
  give the current figure and describe the change (with both periods), rather than repeating the old one.
- When you rely on an earlier conversation, say so and give its date, e.g. "(from our 2 Oct conversation)".
- Never present a figure from an earlier conversation as current unless current research confirms it."""


def _citations(findings: list[SkillFinding]) -> list[Citation]:
    seen: dict[str, Citation] = {}
    for f in findings:
        for c in f.citations:
            seen.setdefault(c.url or c.title, c)
    return list(seen.values())


def referenced_titles(reference_context: str) -> list[str]:
    """Titles of the referenced conversations, parsed from the context-pack headers."""
    return re.findall(r'^=== EARLIER CONVERSATION "(.*)" \(id ', reference_context, flags=re.M)


def rule_based_answer(
    findings: list[SkillFinding], deltas: list[MetricDelta], issues: list[ValidationIssue],
    reference_context: str = "",
) -> str:
    """Demo-mode answer: a structured digest of the relevant findings."""
    if not findings:
        return "I don't have research for that yet - try asking about rents, vacancy, take-up, supply, submarkets, macro, occupier demand or news."
    # Blocks are joined with blank lines so Markdown does not glue a paragraph
    # onto the preceding bullet list.
    blocks = ["*(Demo mode - answer assembled from canned research without an LLM.)*"]
    titles = referenced_titles(reference_context)
    if titles:
        # Demo mode can't reason over earlier conversations; it shows what would be used.
        blocks.append("**Referenced earlier conversations** (background; current research below takes precedence)\n\n"
                      + "\n".join(f"- {t}" for t in titles))
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
    reference_context = state.get("reference_context") or ""

    if get_settings().cre_demo_mode:
        answer = rule_based_answer(findings, deltas, issues, reference_context)
    else:
        system = ANSWER_PROMPT.format(
            findings="\n".join(finding_to_json(f) for f in findings) or "(none - answer from conversation)",
            deltas="\n".join(d.describe() for d in deltas if d.is_material) or "(none)",
            issues="\n".join(f"- {i.message}" for i in issues) or "(none)",
            references=REFERENCES_PROMPT.format(packs=reference_context) if reference_context else "",
        )
        try:
            reply = get_llm("synthesis").invoke([SystemMessage(system), *state.get("messages", [])])
            answer = reply.content if isinstance(reply.content, str) else "".join(
                b.get("text", "") for b in reply.content if isinstance(b, dict)
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Chat answer LLM failed; returning digest")
            answer = rule_based_answer(findings, deltas, issues, reference_context) + f"\n\n_(LLM error: {exc})_"
    return {"answer": answer, "messages": [AIMessage(answer)]}
