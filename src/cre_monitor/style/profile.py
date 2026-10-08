"""House style: learn how a set of example reports is written, then reuse it.

Flow::

    style/reports/*.md|txt|html|pdf  --(cre-monitor style learn)-->  style/profile.json (+ profile.md)
                                                                           |
          synthesis prompt (executive summary) <---------------------------+
          style editor (topic headlines / summaries / insights) <----------+
          report layout (section order + headings) <-----------------------+

The profile **describes** a style (voice, structure, techniques, conventions);
it never stores copied passages - example sentences are short paraphrases. That
keeps the feature on the right side of copyright when the reservoir contains
licensed broker reports (which is also why ``style/reports/`` is git-ignored).

Learning uses the synthesis-tier LLM when available; otherwise (demo mode / no
key) a deterministic heuristic derives headings, sentence length, bullet use and
number conventions, so the feature works and is testable offline.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from cre_monitor.config import get_settings

logger = logging.getLogger(__name__)

#: Report sections the layout can order. KPI tiles have no heading.
SectionId = Literal["kpis", "summary", "what_changed", "risks", "charts", "topics",
                    "watch_list", "data_quality", "sources"]

#: Built-in layout (used when no profile exists, and to fill in sections a profile omits).
DEFAULT_LAYOUT: list[tuple[str, str]] = [
    ("kpis", ""), ("summary", "Executive summary"), ("what_changed", "What changed"),
    ("risks", "Risks & opportunities"), ("charts", "Market charts"), ("topics", "Research by topic"),
    ("watch_list", "Watch list"), ("data_quality", "Data quality notes"), ("sources", "Sources"),
]

SUPPORTED_SUFFIXES = {".md", ".txt", ".html", ".htm", ".pdf"}
#: Per-file excerpt budget sent to the LLM (keeps learning cheap and bounded).
EXCERPT_CHARS = 6000
MAX_FILES = 8


class LayoutSection(BaseModel):
    """One section in the house layout."""

    section: SectionId
    title: str = Field(description="Heading to use, e.g. 'Key themes'. Empty for KPI tiles.")


class StyleProfile(BaseModel):
    """How the example reports are written - used to steer our brief."""

    name: str = Field(description="Short label, e.g. 'House style learned from 3 reports'.")
    sources: list[str] = Field(default_factory=list, description="File names the profile was learned from.")
    learned_at: str = Field(default="", description="ISO timestamp.")
    method: str = Field(default="llm", description="'llm' or 'heuristic'.")
    voice: str = Field(description="Tone, register and person, e.g. 'authoritative, concise, third person'.")
    audience: str = Field(default="", description="Who the reports are written for.")
    layout: list[LayoutSection] = Field(default_factory=list, description="Section order and headings.")
    headline_style: str = Field(default="", description="How headlines / key messages are written.")
    paragraph_style: str = Field(default="", description="Length, prose vs bullets, use of sub-headings.")
    number_style: str = Field(default="", description="Conventions, e.g. '£190 psf', 'bp', 'm sq ft', 'Q2 2026'.")
    techniques: list[str] = Field(default_factory=list, description="Signature techniques, imperative form.")
    preferred_phrases: list[str] = Field(default_factory=list, description="Short generic phrases typical of the style.")
    avoid: list[str] = Field(default_factory=list, description="Things the style avoids.")
    example_sentences: list[str] = Field(
        default_factory=list, description="Up to 5 SHORT paraphrased sentences showing the style (never verbatim).",
    )

    def prompt_text(self) -> str:
        """The profile as instructions for an LLM writing in this style."""
        parts = [f"HOUSE STYLE ({self.name}) - write in this style, but never copy text from any source:",
                 f"- Voice: {self.voice}"]
        for label, value in (("Audience", self.audience), ("Headlines", self.headline_style),
                             ("Paragraphs", self.paragraph_style), ("Numbers", self.number_style)):
            if value:
                parts.append(f"- {label}: {value}")
        if self.techniques:
            parts.append("- Techniques: " + "; ".join(self.techniques))
        if self.preferred_phrases:
            parts.append("- Typical phrasing: " + "; ".join(self.preferred_phrases))
        if self.avoid:
            parts.append("- Avoid: " + "; ".join(self.avoid))
        if self.example_sentences:
            parts.append("- Example sentences (style only, do not reuse): " + " | ".join(self.example_sentences))
        return "\n".join(parts)

    def to_markdown(self) -> str:
        """Human-readable version written next to profile.json (for review)."""
        lines = [f"# {self.name}", "", f"_Learned {self.learned_at} by {self.method} from: "
                 f"{', '.join(self.sources) or '-'}_", "", f"**Voice:** {self.voice}"]
        for label, value in (("Audience", self.audience), ("Headlines", self.headline_style),
                             ("Paragraphs", self.paragraph_style), ("Numbers", self.number_style)):
            if value:
                lines.append(f"**{label}:** {value}")
        if self.layout:
            lines += ["", "## Layout"] + [f"{i}. `{s.section}` - {s.title or '(no heading)'}"
                                          for i, s in enumerate(self.layout, 1)]
        for title, items in (("Techniques", self.techniques), ("Typical phrasing", self.preferred_phrases),
                             ("Avoid", self.avoid), ("Example sentences (paraphrased)", self.example_sentences)):
            if items:
                lines += ["", f"## {title}"] + [f"- {i}" for i in items]
        lines += ["", "_Edit profile.json to adjust; this file is regenerated from it._"]
        return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------

def style_dir() -> Path:
    return get_settings().style_dir


def profile_path() -> Path:
    return style_dir() / "profile.json"


def load_profile() -> StyleProfile | None:
    """The saved profile, or None (no profile / unreadable - logged, never fatal)."""
    path = profile_path()
    if not path.exists():
        return None
    try:
        return StyleProfile.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        logger.warning("Ignoring invalid style profile %s: %s", path, exc)
        return None


def save_profile(profile: StyleProfile) -> Path:
    """Write profile.json and the readable profile.md."""
    path = profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    path.with_suffix(".md").write_text(profile.to_markdown(), encoding="utf-8")
    return path


def active_profile(enabled: bool = True) -> StyleProfile | None:
    """The profile to apply to a report, or None.

    Args:
        enabled: Per-run switch (``AgentState.use_style``: CLI ``--no-style``, the UI's
            "Use house style" toggle). Both it and the global ``REPORT_STYLE``
            setting must be on.
    """
    return load_profile() if enabled and get_settings().report_style else None


def resolve_layout(profile: StyleProfile | None) -> list[tuple[str, str]]:
    """Section order + headings for rendering.

    The profile's order comes first. Sections it doesn't mention are added with
    their default headings (content is never dropped): content sections go just
    before the trailing reference sections (data quality notes, sources), which
    always stay at the end of the report.
    """
    if profile is None or not profile.layout:
        return list(DEFAULT_LAYOUT)
    defaults = dict(DEFAULT_LAYOUT)
    trailing = ("data_quality", "sources")
    seen, out = set(), []
    for s in profile.layout:
        if s.section not in seen:
            seen.add(s.section)
            out.append((s.section, s.title if s.section != "kpis" else ""))
    missing = [(sid, title) for sid, title in DEFAULT_LAYOUT if sid not in seen]
    missing_content = [m for m in missing if m[0] not in trailing]
    missing_trailing = [m for m in missing if m[0] in trailing]
    # Insert missing content before the first trailing section the profile placed (if any).
    cut = next((i for i, (sid, _) in enumerate(out) if sid in trailing), len(out))
    out = out[:cut] + missing_content + out[cut:] + missing_trailing
    return [(sid, title or defaults[sid]) for sid, title in out]


# --------------------------------------------------------------------------
# Reading the reservoir
# --------------------------------------------------------------------------

def read_example(path: Path) -> str:
    """Plain text of one example report (markdown/text/HTML/PDF)."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        return "\n\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    raw = path.read_text(encoding="utf-8", errors="replace")
    if suffix in {".html", ".htm"}:
        import trafilatura

        return trafilatura.extract(raw, include_tables=True, output_format="markdown") or ""
    return raw


def examples_dir() -> Path:
    """Where example reports live (``style/reports/``, git-ignored except its README)."""
    return style_dir() / "reports"


def list_examples(folder: Path | None = None) -> list[Path]:
    """Supported example reports in ``folder`` (default :func:`examples_dir`), README excluded."""
    folder = folder or examples_dir()
    if not folder.exists():
        return []
    return sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
                  and p.name.lower() != "readme.md")


def _safe_example_path(name: str) -> Path:
    """Path for an example file in :func:`examples_dir`, rejecting unsafe or unsupported names.

    Only the base name is kept (an uploaded "../../x.md" becomes "x.md"), so a
    file can never be written or deleted outside the examples folder.
    """
    base = Path(name.replace("\\", "/")).name.strip()
    if not base or base.startswith(".") or base.lower() == "readme.md":
        raise ValueError(f"Not a valid example file name: {name!r}")
    if Path(base).suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported file type {Path(base).suffix or '(none)'}; "
                         f"use {', '.join(sorted(SUPPORTED_SUFFIXES))}")
    return examples_dir() / base


def save_example(name: str, data: bytes) -> Path:
    """Save one example report (e.g. a UI upload) into :func:`examples_dir`. Overwrites same name."""
    path = _safe_example_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def delete_example(name: str) -> bool:
    """Delete one example report by file name. True if it existed."""
    path = _safe_example_path(name)
    existed = path.exists()
    path.unlink(missing_ok=True)
    return existed


# --------------------------------------------------------------------------
# Learning
# --------------------------------------------------------------------------

#: Heading keywords -> section id (heuristic layout detection).
_SECTION_KEYWORDS: list[tuple[str, str]] = [
    ("summary", r"summary|overview|key (themes|points|messages|takeaways)|at a glance|highlights"),
    ("what_changed", r"what changed|changes|quarter in review|this quarter"),
    ("risks", r"risk|opportunit|outlook and risks"),
    ("charts", r"chart|figure|graph"),
    ("watch_list", r"watch|outlook|look ahead|next steps|forecast"),
    ("data_quality", r"methodolog|data quality|notes|definitions"),
    ("sources", r"source|reference|contact"),
    ("topics", r"market|leasing|take-up|rents?|vacancy|supply|pipeline|submarket|demand|investment|occupier"),
]


def _headings(text: str) -> list[str]:
    found = re.findall(r"^\s{0,3}#{1,3}\s+(.+?)\s*#*$", text, flags=re.M)
    if not found:  # PDFs / plain text: short title-like lines
        found = [ln.strip() for ln in text.splitlines()
                 if 3 <= len(ln.strip()) <= 60 and ln.strip()[:1].isupper() and not ln.strip().endswith(".")
                 and len(ln.split()) <= 7][:40]
    return found


def heuristic_profile(texts: dict[str, str]) -> StyleProfile:
    """Deterministic profile from simple text statistics (no LLM)."""
    corpus = "\n".join(texts.values())
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", corpus)) if len(s.split()) >= 4]
    avg_len = round(sum(len(s.split()) for s in sentences) / max(len(sentences), 1))
    lines = [ln for ln in corpus.splitlines() if ln.strip()]
    bullet_ratio = sum(bool(re.match(r"\s*([-*•]|\d+\.)\s", ln)) for ln in lines) / max(len(lines), 1)
    # Share of sentences written in the first person plural (relative, so it scales with length).
    we_share = sum(bool(re.search(r"\b(we|our)\b", s, flags=re.I)) for s in sentences) / max(len(sentences), 1)

    layout, seen = [], set()
    for title in (h for t in texts.values() for h in _headings(t)):
        for sid, pattern in _SECTION_KEYWORDS:
            if sid not in seen and re.search(pattern, title, flags=re.I):
                seen.add(sid)
                layout.append(LayoutSection(section=sid, title=title[:60]))
                break

    conventions = []
    if re.search(r"\bpsf\b", corpus, flags=re.I):
        conventions.append("rents as '£X psf'")
    elif re.search(r"per sq\.? ?ft", corpus, flags=re.I):
        conventions.append("rents as '£X per sq ft'")
    if re.search(r"\d\s?bps?\b", corpus):
        conventions.append("yield / rate moves in basis points (bp)")
    if re.search(r"\d(\.\d+)?\s?m sq ft", corpus):
        conventions.append("areas in 'm sq ft'")
    if re.search(r"\bQ[1-4] 20\d\d\b", corpus):
        conventions.append("periods as 'Q2 2026'")

    techniques = [
        f"Keep sentences around {avg_len} words" + (" (short, punchy)" if avg_len <= 18 else ""),
        "Lead with bullet-point key messages" if bullet_ratio > 0.25 else "Write mainly in prose paragraphs",
    ]
    if re.search(r"long[- ]term average|10-year average|five-year average", corpus, flags=re.I):
        techniques.append("Benchmark figures against long-term averages")
    if re.search(r"year[- ]on[- ]year|y/y|q/q|quarter[- ]on[- ]quarter", corpus, flags=re.I):
        techniques.append("Quote changes year on year / quarter on quarter")
    return StyleProfile(
        name=f"House style learned from {len(texts)} report(s) (heuristic)",
        sources=list(texts), learned_at=datetime.now().isoformat(timespec="seconds"), method="heuristic",
        voice=("first person plural ('we')" if we_share >= 0.15 else "impersonal third person")
              + ", professional and factual",
        layout=layout,
        paragraph_style=f"average sentence {avg_len} words; {round(bullet_ratio * 100)}% of lines are bullets",
        number_style=", ".join(conventions) or "as in the source data",
        techniques=techniques,
    )


LEARN_PROMPT = """You are an editor analysing the WRITING STYLE of professional real estate market reports.
Describe how they are written so another writer can imitate the style - NOT their content.

Rules:
- Describe characteristics; never copy sentences. Example sentences must be your own short paraphrases
  (max 25 words each, max 5) that demonstrate the style with neutral content.
- layout: the order of the main sections, mapped onto these section ids where they fit:
  kpis (headline figures panel), summary, what_changed, risks, charts, topics (per-topic analysis),
  watch_list (outlook / what to watch), data_quality (notes / methodology), sources. Use the reports' own
  heading wording as the title. Omit sections the reports don't have.
- techniques: concrete, reusable instructions (e.g. "Open each section with the key number, then the comparison
  with the 10-year average"), not vague adjectives.
- number_style: exact conventions seen (units, abbreviations, period format, decimals).
"""


def llm_profile(texts: dict[str, str]) -> StyleProfile:
    """Profile written by the synthesis-tier LLM from bounded excerpts."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from cre_monitor.llm import STRUCTURED, get_llm

    excerpts = "\n\n".join(f"=== REPORT: {name} ===\n{text[:EXCERPT_CHARS]}" for name, text in texts.items())
    model = get_llm("synthesis").with_structured_output(StyleProfile, **STRUCTURED)
    profile: StyleProfile = model.invoke([SystemMessage(LEARN_PROMPT), HumanMessage(excerpts)])
    profile.sources = list(texts)
    profile.learned_at = datetime.now().isoformat(timespec="seconds")
    profile.method = "llm"
    return profile


def learn_profile(folder: Path | None = None, *, use_llm: bool | None = None) -> StyleProfile:
    """Learn and save a profile from the reports in ``folder`` (default ``style/reports``).

    Args:
        folder: Folder with example reports.
        use_llm: Force LLM (True) or heuristic (False); default = LLM unless demo mode.

    Raises:
        ValueError: No supported example reports found.
    """
    files = list_examples(folder)[:MAX_FILES]
    if not files:
        raise ValueError(f"No example reports (.md/.txt/.html/.pdf) found in {folder or examples_dir()}")
    texts = {p.name: read_example(p) for p in files}
    texts = {k: v for k, v in texts.items() if v.strip()}
    if not texts:
        raise ValueError("The example reports contain no extractable text (scanned PDFs?)")
    if use_llm is None:
        use_llm = not get_settings().cre_demo_mode
    if use_llm:
        try:
            profile = llm_profile(texts)
        except Exception as exc:  # noqa: BLE001 - fall back rather than fail
            logger.warning("LLM style learning failed (%s); using heuristic profile", exc)
            profile = heuristic_profile(texts)
    else:
        profile = heuristic_profile(texts)
    save_profile(profile)
    logger.info("Learned style profile from %d report(s) via %s", len(texts), profile.method)
    return profile


def clear_profile() -> bool:
    """Delete the saved profile (reports return to the default style). True if one existed."""
    existed = profile_path().exists()
    for p in (profile_path(), profile_path().with_suffix(".md")):
        p.unlink(missing_ok=True)
    return existed
