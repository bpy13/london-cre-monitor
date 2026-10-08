"""Brief quality judge: rate an existing brief against a reference report (one Claude call).

The judge sees the reference's key themes and accepted figures (from its answer
key) and the brief's Markdown, and returns a rubric:

=================  ==============================================================
theme coverage     each reference theme: covered / partly / missing (+ note)
consistency 1-5    no contradiction with the reference figures (period-aware)
so-what 1-5        implications for a London office landlord / investor (Nan Fung)
structure 1-5      easy to navigate, headline first, sections fit the content
readability 1-5    plain, precise English; figures with units and periods
=================  ==============================================================

Scores are an AI opinion: use them to compare briefs and runs (same reference,
same rubric), not as absolute grades, and spot-check a sample by hand.
The free, deterministic parts of a judgement (readability statistics, citation
check of the brief's figures) are computed in :mod:`cre_monitor.benchmark.runner`.
"""

from __future__ import annotations

from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from cre_monitor.config import get_settings

#: Characters of the brief sent to the judge (~8k tokens).
MAX_BRIEF_CHARS = 30_000


class ThemeVerdict(BaseModel):
    theme: str
    coverage: Literal["covered", "partly", "missing"]
    note: str = ""


class Score(BaseModel):
    score: int = Field(ge=1, le=5)
    reason: str


class BriefJudgement(BaseModel):
    """The judge's rubric for one brief against one reference report."""

    themes: list[ThemeVerdict]
    consistency: Score
    so_what: Score
    structure: Score
    readability: Score
    contradictions: list[str] = Field(default_factory=list,
                                      description="Figures in the brief that contradict the reference for the same period.")
    summary: str = Field(description="Two sentences: main strength and main gap.")

    @property
    def theme_coverage(self) -> float | None:
        """Percentage: covered = 1, partly = 0.5."""
        if not self.themes:
            return None
        pts = sum({"covered": 1.0, "partly": 0.5}.get(t.coverage, 0.0) for t in self.themes)
        return round(100 * pts / len(self.themes), 1)


JUDGE_PROMPT = """You evaluate a London office market brief written by an AI research agent for Nan Fung Group
(a long-term London office investor and developer), using a reference report as the benchmark.

- For EACH reference theme, say whether the brief covers it (covered / partly / missing), with a short note.
- consistency: 5 = no figure contradicts the reference for the same period, place and definition; differences that
  are clearly due to a different source or period are NOT contradictions. List real contradictions.
- so_what: are implications for a landlord/investor/developer clear and specific?
- structure and readability: judge for a busy senior reader.
Be strict and specific; reasons in one or two sentences."""


def judge_brief(key, brief_markdown: str) -> BriefJudgement:
    """Rate ``brief_markdown`` against answer key ``key`` (live mode, skill tier).

    Raises:
        NeedsLiveMode: demo mode.
        ValueError: the key has no themes or accepted figures to judge against.
    """
    from cre_monitor.authoring import NeedsLiveMode

    if get_settings().cre_demo_mode:
        raise NeedsLiveMode("The brief quality judge needs Claude (live mode).")
    if not key.themes and not key.accepted():
        raise ValueError("The answer key has no themes or accepted figures to judge against.")
    from cre_monitor.llm import STRUCTURED, get_llm  # read at call time so tests can patch it

    figures = "\n".join(f"- {e.key} | {e.submarket} | {e.period} | {e.value:g} {e.unit} | {e.source}"
                        for e in key.accepted())
    reference = (f"REFERENCE: {key.title} ({key.publisher}, {key.period})\nTHEMES:\n"
                 + "\n".join(f"- {t}" for t in key.themes) + f"\nACCEPTED FIGURES:\n{figures or '(none)'}")
    return get_llm("skill").with_structured_output(BriefJudgement, **STRUCTURED).invoke([
        SystemMessage(JUDGE_PROMPT),
        HumanMessage(f"{reference}\n\nBRIEF TO EVALUATE (Markdown):\n{brief_markdown[:MAX_BRIEF_CHARS]}"),
    ])
