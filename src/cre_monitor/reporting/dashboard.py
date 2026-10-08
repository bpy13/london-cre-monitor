"""Data selection and charts for the UI's Dashboard tab (pure functions, unit-tested).

For one metric the Dashboard shows:

1. **Headline**: latest value for the main place (Central London, else UK, ...),
   with the change since the previous period *from the same source, same period
   length* (:func:`headline`).
2. **Latest by submarket**: a bar per place, using one consistent source where
   possible. Works even when only one period has been recorded
   (:func:`latest_by_place`, :func:`snapshot_chart`).
3. **Trend**: one line per chosen place on a real date axis (:func:`trend_figure`).
   Each line follows one source and one period length (:func:`line_for`); up to
   4 places share one chart, more become small multiples (one panel each), so
   any number of submarkets stays readable.

How a line is chosen (shown to users in "How to read this"):

* The **source** is the one picked in the UI, or else the source with the most
  observations for that place (brokers define metrics differently, so one
  line = one broker).
* Only that source's most common **period length** is drawn (a half-year total
  never joins a quarterly one).
* If no single source has 2+ points, periods from different sources are
  stitched together and the line is dashed ("mixed sources").
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from cre_monitor.catalog import MetricDef
from cre_monitor.periods import FREQ_NAMES, parse_period
from cre_monitor.reporting.charts import BASELINE, FONT, GRID, INK_MUTED, INK_PRIMARY, INK_SECONDARY, SERIES, \
    SUBMARKET_COLORS

#: Up to this many places share one trend chart; more become small multiples.
MAX_OVERLAY = 4
#: Preferred "main place" for the headline, in order.
HEADLINE_PLACES = ["Central London", "UK", "London"]


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------

def format_value(value: float | None, unit: str) -> str:
    """Human-friendly number for ``unit``: £190.00 psf, 6.3%, 2.6m sq ft, £1.2bn, 9 months."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "–"
    v = float(value)
    if unit == "GBP psf pa":
        return f"£{v:,.2f} psf"
    if unit == "%":
        return f"{v:.2f}%" if abs(v) < 10 and v != round(v, 1) else f"{v:.1f}%"
    if unit == "sq ft":
        return f"{v / 1e6:.2f}m sq ft" if abs(v) >= 1e6 else f"{v / 1e3:,.0f}k sq ft" if abs(v) >= 1e4 else f"{v:,.0f} sq ft"
    if unit == "GBP":
        return f"£{v / 1e9:.2f}bn" if abs(v) >= 1e9 else f"£{v / 1e6:,.0f}m" if abs(v) >= 1e6 else f"£{v:,.0f}"
    return f"{v:,.4g} {unit}".strip()


def format_change(current: float, previous: float, unit: str) -> str:
    """Change text: percentage points for rates, % change otherwise (e.g. '+0.25pp', '-3.1%')."""
    if unit == "%":
        return f"{current - previous:+.2f}pp"
    if previous == 0:
        return "n/a"
    return f"{100 * (current - previous) / abs(previous):+.1f}%"


# --------------------------------------------------------------------------
# Data selection
# --------------------------------------------------------------------------

def prepare(series: pd.DataFrame) -> pd.DataFrame:
    """Add parsed period columns to ``MetricsStore.series`` output.

    Adds ``end`` (period end date, NaT if unparseable), ``freq`` (period length
    code) and keeps only parseable rows - unrecognised labels can't be placed
    on a time axis and are listed in the data table only.
    """
    if series is None or series.empty:
        return pd.DataFrame(columns=["submarket", "period", "value", "unit", "source", "end", "freq"])
    parsed = series["period"].map(parse_period)
    out = series.assign(end=parsed.map(lambda p: pd.Timestamp(p.end) if p else pd.NaT),
                        freq=parsed.map(lambda p: p.freq if p else None))
    return out[out["end"].notna()].sort_values(["end", "source"]).reset_index(drop=True)


def sources_by_coverage(df: pd.DataFrame) -> list[str]:
    """Sources ordered by how many (place, period) points they cover, most first."""
    if df.empty:
        return []
    counts = df.groupby("source").size().sort_values(ascending=False, kind="stable")
    return list(counts.index)


def latest_by_place(df: pd.DataFrame, source: str | None = None) -> pd.DataFrame:
    """One row per place: its latest period, from ``source`` if given, else the best-covered source.

    A place without data from the chosen source is left out (like-for-like bars).
    """
    if df.empty:
        return df
    rank = {s: i for i, s in enumerate(sources_by_coverage(df))}
    d = df[df["source"] == source] if source else df
    rows = []
    for place, g in d.groupby("submarket"):
        latest = g[g["end"] == g["end"].max()]
        rows.append(latest.loc[latest["source"].map(rank).idxmin()])
    return pd.DataFrame(rows).reset_index(drop=True) if rows else d.iloc[0:0]


def default_place(df: pd.DataFrame) -> str | None:
    """The place the headline describes: Central London, else UK/London, else the best-covered place."""
    if df.empty:
        return None
    places = set(df["submarket"])
    return next((p for p in HEADLINE_PLACES if p in places), df["submarket"].value_counts().index[0])


@dataclass
class Headline:
    """Latest value and change for one place (one source, one period length)."""

    place: str
    value: float
    period: str
    source: str
    previous: float | None = None
    previous_period: str | None = None


def headline(df: pd.DataFrame, place: str | None = None, source: str | None = None) -> Headline | None:
    """Latest figure for ``place`` and the previous one from the same source and period length."""
    place = place or default_place(df)
    d = df[df["submarket"] == place]
    if source:
        d = d[d["source"] == source]
    if d.empty:
        return None
    latest = latest_by_place(d).iloc[0]
    same = d[(d["source"] == latest["source"]) & (d["freq"] == latest["freq"]) & (d["end"] < latest["end"])]
    prev = same.iloc[-1] if not same.empty else None
    return Headline(place=place, value=float(latest["value"]), period=str(latest["period"]),
                    source=str(latest["source"]),
                    previous=float(prev["value"]) if prev is not None else None,
                    previous_period=str(prev["period"]) if prev is not None else None)


@dataclass
class Line:
    """The points drawn for one place, and why."""

    place: str
    rows: pd.DataFrame
    source: str          # the source used, or "mixed"
    mixed: bool          # stitched from several sources (drawn dashed)
    freq: str            # period length drawn
    left_out: int        # points not drawn (other sources / other period lengths)


def line_for(d: pd.DataFrame, place: str, source: str | None = None) -> Line | None:
    """Choose the points for ``place`` (see module docstring). None if nothing to draw."""
    d = d[d["submarket"] == place]
    if d.empty:
        return None
    if source:
        pool, mixed = d[d["source"] == source], False
        if pool.empty:
            return None
    else:
        counts = d.groupby(["source", "freq"]).size().sort_values(ascending=False, kind="stable")
        (best_src, _), n = counts.index[0], counts.iloc[0]
        if n >= 2:
            pool, mixed = d[d["source"] == best_src], False
        else:
            pool, mixed = d, True
    freq = pool["freq"].value_counts().index[0]
    pool = pool[pool["freq"] == freq]
    if mixed:
        # One point per period, preferring the overall best-covered source.
        rank = {s: i for i, s in enumerate(sources_by_coverage(d))}
        pool = pool.assign(_r=pool["source"].map(rank)).sort_values(["end", "_r"]).drop_duplicates("end")
        mixed = pool["source"].nunique() > 1
    pool = pool.sort_values("end")
    used = "mixed" if mixed else str(pool["source"].iloc[0])
    return Line(place=place, rows=pool, source=used, mixed=mixed, freq=freq, left_out=len(d) - len(pool))


# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------

def _style(fig: go.Figure, title: str, height: int) -> go.Figure:
    fig.update_layout(
        title={"text": title, "x": 0, "xanchor": "left", "font": {"size": 15, "color": INK_PRIMARY}},
        font={"family": FONT, "size": 12, "color": INK_SECONDARY},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=height,
        margin={"l": 10, "r": 30, "t": 60, "b": 40}, hoverlabel={"font": {"family": FONT}},
        legend={"orientation": "h", "y": 1.02, "yanchor": "bottom", "x": 0, "title": None},
    )
    axis = dict(gridcolor=GRID, linecolor=BASELINE, tickfont={"color": INK_MUTED}, zeroline=False)
    fig.update_xaxes(**axis, showgrid=False)
    fig.update_yaxes(**axis)
    return fig


def place_colors(places: list[str]) -> dict[str, str]:
    """Fixed colour per known submarket; others take the first palette colour not already used here."""
    colors = {p: SUBMARKET_COLORS[p] for p in places if p in SUBMARKET_COLORS}
    free = [c for c in SERIES if c not in colors.values()]
    for p in places:
        if p not in colors:
            colors[p] = free.pop(0) if free else SERIES[-1]
    return colors


def snapshot_chart(latest: pd.DataFrame, metric: MetricDef) -> go.Figure | None:
    """Horizontal bars, one per place, sorted by value (needs 2+ places)."""
    if latest is None or len(latest) < 2:
        return None
    d = latest.sort_values("value")
    labels = [format_value(v, metric.unit) for v in d["value"]]
    hover = [f"{p}: {lab}<br>{per} · {src}" for p, lab, per, src in zip(d["submarket"], labels, d["period"], d["source"])]
    fig = go.Figure(go.Bar(
        x=d["value"], y=d["submarket"], orientation="h", marker={"color": SERIES[0], "cornerradius": 4},
        text=labels, textposition="outside", textfont={"color": INK_SECONDARY}, cliponaxis=False,
        hovertext=hover, hoverinfo="text",
    ))
    lo = min(0.0, float(d["value"].min()))
    fig.update_xaxes(showgrid=True, gridcolor=GRID, range=[lo * 1.18, float(d["value"].max()) * 1.18],
                     title={"text": f"{metric.unit} · source: {', '.join(sorted(d['source'].unique()))}",
                            "font": {"color": INK_MUTED}})
    fig = _style(fig, f"{metric.label}: latest by submarket", height=max(240, 40 * len(d) + 110))
    fig.update_layout(margin={"r": 90})
    return fig


def trend_figure(df: pd.DataFrame, places: list[str], metric: MetricDef,
                 source: str | None = None) -> tuple[go.Figure | None, list[Line]]:
    """Trend lines on a date axis: one chart for <= 4 places, small multiples beyond.

    Returns:
        ``(figure or None, the lines drawn)``. Places with fewer than 2 points are skipped.
    """
    lines = [ln for p in places if (ln := line_for(df, p, source)) is not None and len(ln.rows) >= 2]
    if not lines:
        return None, []
    colors = place_colors([ln.place for ln in lines])
    title = f"{metric.label} over time ({metric.unit})"
    if any(ln.mixed for ln in lines):
        title += " · dashed = mixed sources"

    def trace(ln: Line, show_legend: bool) -> go.Scatter:
        r = ln.rows
        hover = [f"{ln.place}<br>{per}: {format_value(v, metric.unit)}<br>{src}"
                 for per, v, src in zip(r["period"], r["value"], r["source"])]
        return go.Scatter(
            x=r["end"], y=r["value"], mode="lines+markers", showlegend=show_legend,
            name=ln.place + (" (mixed sources)" if ln.mixed else f" ({ln.source})"),
            line={"color": colors[ln.place], "width": 2, "dash": "dash" if ln.mixed else "solid"},
            marker={"size": 8, "color": colors[ln.place], "line": {"width": 2, "color": "#fcfcfb"}},
            hovertext=hover, hoverinfo="text",
        )

    if len(lines) <= MAX_OVERLAY:
        fig = go.Figure([trace(ln, True) for ln in lines])
        for ln in lines:  # direct label at the line end (identity never by colour alone)
            fig.add_annotation(x=ln.rows["end"].iloc[-1], y=ln.rows["value"].iloc[-1], text=ln.place,
                               showarrow=False, xanchor="left", xshift=8, font={"size": 11, "color": INK_SECONDARY})
        fig = _style(fig, title, 400)
        fig.update_layout(margin={"r": 120}, hovermode="closest")
        return fig, lines

    cols = 3
    rows = math.ceil(len(lines) / cols)
    fig = make_subplots(rows=rows, cols=cols, shared_xaxes=True, shared_yaxes=True,
                        subplot_titles=[ln.place for ln in lines], vertical_spacing=0.12, horizontal_spacing=0.04)
    for i, ln in enumerate(lines):
        fig.add_trace(trace(ln, False), row=i // cols + 1, col=i % cols + 1)
    fig = _style(fig, title + " · one panel per submarket, same scale", 230 * rows + 80)
    fig.update_annotations(font={"size": 12, "color": INK_SECONDARY})  # panel titles
    return fig, lines


def freq_name(code: str) -> str:
    return FREQ_NAMES.get(code, code)
