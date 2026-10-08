"""Pure scoring functions for the performance check (no LLM, no I/O - unit-tested).

* :func:`numbers_in_text` / :func:`value_in_text` - find a figure in free text,
  understanding scale words ("2.5m sq ft" == 2,500,000; "£1.2bn"; "6.3%").
  Used three ways: is an answer-key figure really in the reference report
  (moderation), did the agent see the figure in a tool result (grounding), and
  does the cited page contain it (citation check).
* :func:`score_figures` - compare the agent's metrics with the accepted
  answer-key entries: coverage, accuracy (same source vs other source), error,
  period and unit correctness, grounding.
* :func:`readability` - simple, explainable readability statistics.

Definitions are repeated in docs/EVALUATION.md; keep both in sync.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cre_monitor.periods import parse_period
from cre_monitor.schemas import Metric

_SCALE = {"bn": 1e9, "billion": 1e9, "m": 1e6, "mn": 1e6, "million": 1e6, "k": 1e3, "thousand": 1e3}
_NUM_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(bn|billion|mn|million|m|k|thousand)?(?![\w])",
                     flags=re.I)


def numbers_in_text(text: str) -> list[float]:
    """Every number in ``text``, with scale words applied ("2.5m" -> 2_500_000, "1,200" -> 1200)."""
    out = []
    for whole, frac, scale in _NUM_RE.findall(text or ""):
        value = float(whole.replace(",", "") + (frac or ""))
        out.append(value * _SCALE.get((scale or "").lower(), 1.0))
    return out


def close(a: float, b: float, rel: float = 0.005) -> bool:
    """Equal within ``rel`` (0.5% by default), so rounding in the text still matches."""
    return abs(a - b) <= max(abs(a), abs(b)) * rel + 1e-9


def value_in_text(value: float, text: str) -> bool:
    """True if ``value`` appears in ``text`` (any formatting/scale)."""
    return any(close(value, n) for n in numbers_in_text(text))


# --------------------------------------------------------------------------
# Figure accuracy
# --------------------------------------------------------------------------

@dataclass
class EntryResult:
    """How the agent did on one answer-key entry."""

    entry_id: str
    expected: float
    found: float | None = None
    found_source: str = ""
    found_url: str = ""
    status: str = "missing"        # accurate | inaccurate | missing
    same_source: bool = False
    pct_error: float | None = None
    unit_ok: bool | None = None
    grounded: bool | None = None   # value present in a tool result the agent saw


@dataclass
class FigureScore:
    """Aggregate figure-accuracy metrics (percentages 0-100; None when undefined)."""

    n_entries: int = 0
    found: int = 0
    accurate: int = 0
    coverage: float | None = None
    accuracy: float | None = None             # of found entries
    accuracy_same_source: float | None = None
    accuracy_other_source: float | None = None
    mean_abs_pct_error: float | None = None
    unit_correct: float | None = None
    grounding: float | None = None            # of ALL figures the agent returned
    n_agent_figures: int = 0
    results: list[EntryResult] = field(default_factory=list)


def _same_period(a: str, b: str) -> bool:
    pa, pb = parse_period(a), parse_period(b)
    if pa and pb:
        return (pa.start, pa.end) == (pb.start, pb.end)
    return a.strip().casefold() == b.strip().casefold()


def _same_source(a: str, b: str) -> bool:
    """Loose publisher match: 'BNP Paribas Real Estate' ~ 'BNP Paribas RE'."""
    a, b = a.casefold(), b.casefold()
    first = lambda s: re.split(r"[\s,(&]+", s.strip())[0] if s.strip() else ""  # noqa: E731
    return bool(a and b) and (a in b or b in a or first(a) == first(b))


def is_accurate(expected: float, found: float, unit: str, tol_pp: float, tol_rel: float) -> bool:
    if unit == "%":
        return abs(found - expected) <= tol_pp + 1e-9
    return abs(found - expected) <= abs(expected) * tol_rel + 1e-9


def match_entry(entry, metrics: list[Metric]) -> Metric | None:
    """The agent's figure for an entry: same key, place and period; same source preferred."""
    candidates = [m for m in metrics if m.key == entry.key and m.submarket == entry.submarket
                  and _same_period(m.period, entry.period)]
    if not candidates:
        return None
    same = [m for m in candidates if _same_source(m.source, entry.source)]
    return (same or candidates)[0]


def score_figures(entries: list, metrics: list[Metric], tool_texts: list[str], *, units: dict[str, str],
                  tol_pp: float = 0.1, tol_rel: float = 0.02) -> FigureScore:
    """Score the agent's ``metrics`` against accepted answer-key ``entries``.

    Args:
        entries: Accepted :class:`~cre_monitor.benchmark.answer_key.KeyEntry` objects.
        metrics: Every metric the agent returned in this run (after validation).
        tool_texts: Contents of every tool result the agent saw (for grounding).
        units: Catalogue units, ``{key: unit}``.
    """
    corpus = "\n".join(tool_texts)
    pct = lambda n, d: round(100 * n / d, 1) if d else None  # noqa: E731
    results, errors = [], []
    for e in entries:
        r = EntryResult(entry_id=e.id, expected=e.value)
        m = match_entry(e, metrics)
        if m is not None:
            r.found, r.found_source, r.found_url = m.value, m.source, m.url
            r.same_source = _same_source(m.source, e.source)
            r.unit_ok = m.unit == units.get(e.key, e.unit)
            r.status = "accurate" if is_accurate(e.value, m.value, units.get(e.key, e.unit), tol_pp, tol_rel) \
                else "inaccurate"
            r.pct_error = round(100 * abs(m.value - e.value) / abs(e.value), 2) if e.value else None
            r.grounded = value_in_text(m.value, corpus)
            if r.pct_error is not None:
                errors.append(r.pct_error)
        results.append(r)

    found = [r for r in results if r.found is not None]
    same = [r for r in found if r.same_source]
    other = [r for r in found if not r.same_source]
    grounded_all = [value_in_text(m.value, corpus) for m in metrics]
    return FigureScore(
        n_entries=len(entries), found=len(found), accurate=sum(r.status == "accurate" for r in found),
        coverage=pct(len(found), len(entries)),
        accuracy=pct(sum(r.status == "accurate" for r in found), len(found)),
        accuracy_same_source=pct(sum(r.status == "accurate" for r in same), len(same)),
        accuracy_other_source=pct(sum(r.status == "accurate" for r in other), len(other)),
        mean_abs_pct_error=round(sum(errors) / len(errors), 2) if errors else None,
        unit_correct=pct(sum(bool(r.unit_ok) for r in found), len(found)),
        grounding=pct(sum(grounded_all), len(grounded_all)), n_agent_figures=len(metrics),
        results=results,
    )


# --------------------------------------------------------------------------
# Readability
# --------------------------------------------------------------------------

_PERIOD_RE = re.compile(r"\b(Q[1-4]|H[12])\b|\b(19|20)\d{2}\b|\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b"
                        r"|year[- ]on[- ]year|quarter|y/y|q/q", flags=re.I)


def _syllables(word: str) -> int:
    """Rough English syllable count (vowel groups, silent final e) - fine for comparisons."""
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    groups = len(re.findall(r"[aeiouy]+", w))
    if w.endswith("e") and groups > 1 and not w.endswith(("le", "ee")):
        groups -= 1
    return max(groups, 1)


@dataclass
class Readability:
    """Readability statistics of a text."""

    words: int = 0
    sentences: int = 0
    flesch: float | None = None             # Flesch reading ease: higher = easier (60-70 plain English)
    avg_sentence_words: float | None = None
    pct_long_sentences: float | None = None  # sentences over 30 words
    pct_figures_with_period: float | None = None  # sentences with a number that also say when


def readability(text: str) -> Readability:
    """Readability of ``text`` (Markdown/HTML tags and table rows are ignored)."""
    clean = re.sub(r"<[^>]+>|\|.*\||!\[.*?\]\(.*?\)|\[([^\]]*)\]\([^)]*\)", r"\1", text or "")
    clean = re.sub(r"^[#>*\-\s]+", "", clean, flags=re.M)
    sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n{2,}", clean) if len(re.findall(r"[A-Za-z]+", s)) >= 3]
    if not sentences:
        return Readability()
    words = [w for s in sentences for w in re.findall(r"[A-Za-z][A-Za-z'-]*", s)]
    n_s, n_w = len(sentences), max(len(words), 1)
    syll = sum(_syllables(w) for w in words)
    with_numbers = [s for s in sentences if re.search(r"\d", re.sub(_PERIOD_RE, "", s))]
    return Readability(
        words=len(words), sentences=n_s,
        flesch=round(206.835 - 1.015 * (n_w / n_s) - 84.6 * (syll / n_w), 1),
        avg_sentence_words=round(n_w / n_s, 1),
        pct_long_sentences=round(100 * sum(len(re.findall(r"[A-Za-z]+", s)) > 30 for s in sentences) / n_s, 1),
        pct_figures_with_period=round(100 * sum(bool(_PERIOD_RE.search(s)) for s in with_numbers)
                                      / len(with_numbers), 1) if with_numbers else None,
    )
