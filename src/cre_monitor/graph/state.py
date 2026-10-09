"""LangGraph state definitions.

``AgentState`` is the shared blackboard passed between nodes. Fields with an
``Annotated[..., reducer]`` type are *merged* when several nodes write to
them in the same step - essential for ``findings``, which is written by N
skill runners executing in parallel.

``SkillTask`` is the (smaller) private input each parallel skill runner
receives via ``Send``; it does not see the whole state.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from cre_monitor.errors import Incident
from cre_monitor.schemas import ExecutiveSynthesis, MetricDelta, SkillFinding, ValidationIssue

Mode = Literal["brief", "chat"]


#: Skill name of the sentinel finding that tells the reducer to overwrite.
_REPLACE_MARKER = "__replace__"


def Replace(findings: list[SkillFinding]) -> list[SkillFinding]:
    """Wrap ``findings`` so the reducer *overwrites* state instead of appending.

    Implemented as a sentinel first element (rather than a list subclass)
    because node outputs are serialised by the checkpointer, and a plain
    pydantic object round-trips safely while a custom list type may not.
    """
    return [SkillFinding(skill=_REPLACE_MARKER, headline="", summary=""), *findings]


def merge_findings(left: list[SkillFinding] | None, right: list[SkillFinding]) -> list[SkillFinding]:
    """Reducer for ``AgentState.findings``.

    * ``Replace([...])`` -> overwrite. The planner sends ``Replace([])`` at the
      start of every run because, with a checkpointer, state persists between
      chat turns and old findings would otherwise pile up. The validator
      sends ``Replace(cleaned)`` after dropping implausible metrics.
    * plain list        -> concatenate (parallel skill runners each add one).
    """
    right = list(right or [])
    if right and right[0].skill == _REPLACE_MARKER:
        return right[1:]
    return (left or []) + right


class AgentState(TypedDict, total=False):
    """Top-level graph state.

    Inputs (set by the caller):
        mode: ``"brief"`` for the full scheduled report, ``"chat"`` for Q&A.
        messages: Conversation history (chat mode). The last human message is
            the question. Merged with ``add_messages`` so the checkpointer
            accumulates multi-turn conversations per ``thread_id``.
        skills_override: Optional explicit list of skills to run (CLI ``--skills``).
        context_refs: Thread ids of earlier conversations referenced in this
            chat turn (validated and capped by ``builder.ask``).
        use_style: Brief mode: apply the learned house style (default True when
            absent). Per run, so one UI user's toggle never affects another's
            brief. The global ``REPORT_STYLE`` setting must also be on.

    Produced by nodes:
        run_id: Unique id of this run (used as key in the metrics store).
        selected_skills: Skills chosen by the planner.
        planner_reasoning: Why those skills were chosen (shown in the UI).
        reference_context: Context packs of the referenced conversations, built by
            the planner. Read by the router and the answer step only - never
            passed to research skills.
        findings: One ``SkillFinding`` per executed skill (parallel-merged).
        validation_issues: Data-quality warnings from the validator.
        deltas: Changes versus earlier periods from the metrics store.
        synthesis: Executive synthesis (brief mode).
        report_paths: Written report files, e.g. ``{"html": ".../brief.html"}``.
        answer: Final chat answer text (chat mode).
        errors: Raw ``"step: error"`` strings from LLM steps that failed outside
            the skills (answer, synthesis). Skill failures live on
            ``SkillFinding.error``. Both are turned into one user-facing
            ``Incident`` (see ``cre_monitor.errors.incident_from_state``).
        incident: That Incident (or None). Set by ``report_writer`` for briefs
            (so the report can show its reference) and by ``builder.ask`` for chat.
    """

    mode: Mode
    messages: Annotated[list[AnyMessage], add_messages]
    skills_override: list[str] | None
    context_refs: list[str]
    use_style: bool

    run_id: str
    selected_skills: list[str]
    planner_reasoning: str
    reference_context: str
    # Parallel skill runners each append; planner/validator overwrite using
    # the ``Replace`` marker (see ``merge_findings``).
    findings: Annotated[list[SkillFinding], merge_findings]
    validation_issues: list[ValidationIssue]
    deltas: list[MetricDelta]
    synthesis: ExecutiveSynthesis | None
    report_paths: dict[str, str]
    answer: str
    errors: list[str]
    incident: Incident | None


class SkillTask(TypedDict):
    """Payload sent to one parallel ``skill_runner`` invocation."""

    skill_name: str
    mode: Mode
    question: str  # the user's question (chat) or a standard brief instruction
