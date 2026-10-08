"""Turn period labels ("2026-Q2", "2026-H1", "2026-08", "2027") into real dates.

Figures are stored with the period they *describe* as free text. Comparing those
strings directly goes wrong in two ways, both seen in real data:

* **Ordering.** As text, "2026-H1" sorts before "2026-Q1", and a text chart axis
  spaces 2025-Q3 -> 2026-Q2 (three quarters) like one quarter.
* **Mixed lengths.** A half-year investment total (2026-H1) followed by a
  quarterly one (2026-Q2) looks like a halving when it isn't.

:func:`parse_period` gives each label a start/end date and a *frequency*, so
charts can use a true time axis and "what changed" only compares like with like.
"""

from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime

#: Frequency codes, shortest first.
FREQ_NAMES = {"D": "daily", "W": "weekly", "M": "monthly", "Q": "quarterly", "H": "half-yearly", "Y": "annual"}


@dataclass(frozen=True)
class Period:
    """A parsed period label."""

    label: str
    start: date
    end: date
    freq: str  # one of FREQ_NAMES

    @property
    def sort_key(self) -> tuple[date, date]:
        return (self.end, self.start)


def _month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def _iso_day(text: str) -> date | None:
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_period(label: str) -> Period | None:
    """Parse a period label, or return None if the format is not recognised.

    Recognised (case-insensitive, surrounding text ignored for the week form):
    ``2026-Q2`` / ``Q2 2026``, ``2026-H1`` / ``H1 2026``, ``2026-08``, ``2026``,
    ``2026-09-25`` (a day) and ``week ending 2026-09-25``.
    """
    s = str(label).strip()
    if m := re.fullmatch(r"(\d{4})-?Q([1-4])|Q([1-4])[ -]?(\d{4})", s, flags=re.I):
        year, q = (int(m[1]), int(m[2])) if m[1] else (int(m[4]), int(m[3]))
        return Period(s, date(year, 3 * q - 2, 1), _month_end(year, 3 * q), "Q")
    if m := re.fullmatch(r"(\d{4})-?H([12])|H([12])[ -]?(\d{4})", s, flags=re.I):
        year, h = (int(m[1]), int(m[2])) if m[1] else (int(m[4]), int(m[3]))
        return Period(s, date(year, 6 * h - 5, 1), _month_end(year, 6 * h), "H")
    if m := re.fullmatch(r"(\d{4})-(\d{2})", s):
        year, month = int(m[1]), int(m[2])
        if 1 <= month <= 12:
            return Period(s, date(year, month, 1), _month_end(year, month), "M")
    if m := re.fullmatch(r"(\d{4})", s):
        year = int(m[1])
        return Period(s, date(year, 1, 1), date(year, 12, 31), "Y")
    if m := re.fullmatch(r"week ending (\d{4}-\d{2}-\d{2})", s, flags=re.I):
        if end := _iso_day(m[1]):
            return Period(s, date.fromordinal(end.toordinal() - 6), end, "W")
    if day := _iso_day(s):
        return Period(s, day, day, "D")
    return None


def period_sort_key(label: str) -> tuple:
    """Sort key putting periods in true time order (unparseable labels last, by text)."""
    p = parse_period(label)
    return (0, p.end, p.start, label) if p else (1, date.max, date.max, str(label))


def same_frequency(a: str, b: str) -> bool:
    """True if both labels parse and have the same frequency (e.g. both quarters)."""
    pa, pb = parse_period(a), parse_period(b)
    return pa is not None and pb is not None and pa.freq == pb.freq
