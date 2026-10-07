"""Plotly charts for the market brief and the chat UI.

Design rules (from the team's data-viz guidelines - keep them when editing):

* **Colour follows the entity, never its rank**: each submarket has a fixed
  colour in :data:`SUBMARKET_COLORS`, so "City" is orange in every chart.
* Categorical colours come from the validated reference palette, assigned in
  fixed order (blue, orange, aqua, yellow, magenta, ...); never generated.
* **One y-axis per chart.** Measures with different units get separate charts.
* Single-series charts carry no legend (the title names the series);
  multi-series charts always have a legend plus end-of-line direct labels.
* Thin marks: 2px lines, >=8px markers, hairline grid, muted axis ink.
* Every chart is interactive (hover tooltips) in HTML; PNG copies are made
  for the Markdown report.
* **Like-for-like sources.** Brokers define metrics differently, so bars are
  drawn from one consistent source where possible and trend lines follow a
  single source. Lines stitched from several sources are dashed and labelled
  "mixed sources" (see :func:`pick_series`). Hover always shows the source.

Each ``*_chart`` function takes plain data and returns a ``go.Figure`` or
``None`` when there is not enough data, so callers can skip it gracefully.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from cre_monitor.schemas import SkillFinding

# --------------------------------------------------------------------------
# Palette (reference instance, light mode; validated for adjacent pairs)
# --------------------------------------------------------------------------
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

#: Fixed entity -> colour mapping (do not reorder: colour must stay stable).
SUBMARKET_COLORS: dict[str, str] = {
    "Central London": SERIES[0],
    "City": SERIES[1],
    "West End": SERIES[2],
    "Canary Wharf": SERIES[3],
    "Midtown": SERIES[4],
    "King's Cross": SERIES[5],
    "Southbank": SERIES[6],
    "Shoreditch & Fringe": SERIES[7],
}
#: Submarkets plotted on trend charts. Capped at 4 lines to stay readable.
TREND_SUBMARKETS = ["Central London", "City", "West End", "Canary Wharf"]


def _style(fig: go.Figure, title: str, y_title: str = "", height: int = 380) -> go.Figure:
    """Apply the shared house style to a figure."""
    fig.update_layout(
        title={"text": title, "x": 0, "xanchor": "left", "font": {"size": 15, "color": INK_PRIMARY}},
        font={"family": FONT, "size": 12, "color": INK_SECONDARY},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=height,
        margin={"l": 10, "r": 30, "t": 60, "b": 40},
        hoverlabel={"font": {"family": FONT}},
        legend={"orientation": "h", "y": 1.02, "yanchor": "bottom", "x": 0, "title": None},
        bargap=0.35,
    )
    axis = dict(gridcolor=GRID, linecolor=BASELINE, tickfont={"color": INK_MUTED}, zeroline=False)
    fig.update_xaxes(**axis, showgrid=False)
    fig.update_yaxes(**axis, title={"text": y_title, "font": {"color": INK_MUTED}})
    return fig


# --------------------------------------------------------------------------
# Data helpers
# --------------------------------------------------------------------------


def metrics_frame(findings: list[SkillFinding]) -> pd.DataFrame:
    """Flatten all metrics from findings into one DataFrame."""
    rows = [
        {"skill": f.skill, **m.model_dump(mode="json")}
        for f in findings if not f.error for m in f.metrics
    ]
    return pd.DataFrame(rows)


def latest_by_submarket(df: pd.DataFrame, key: str) -> pd.DataFrame:
    """Latest-period value of ``key`` per submarket, keeping sources consistent.

    Bars side by side should be like-for-like, so for each submarket we prefer
    the source that covers the most submarkets for this key (e.g. use Avison
    Young for both Central London and Midtown rather than mixing in JLL).
    """
    if df.empty or key not in set(df["key"]):
        return pd.DataFrame()
    sub = df[df["key"] == key].drop_duplicates(["submarket", "period", "source"])
    coverage = sub.groupby("source")["submarket"].nunique()
    sub = sub.assign(_rank=sub["source"].map(coverage)).sort_values(["period", "_rank"])
    # Within the latest period, the last row is the best-covered source.
    latest_period = sub.groupby("submarket")["period"].transform("max")
    sub = sub[sub["period"] == latest_period]
    return sub.groupby("submarket", as_index=False).last().drop(columns="_rank")


def pick_series(d: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """Choose one value per period for a single submarket's history.

    Prefers the source with the most observations, so the line is like-for-like.
    If no single source has 2+ points, falls back to mixing sources (one per
    period, latest-recorded source first) and returns ``mixed=True`` so the
    chart can draw it dashed and say so.

    Returns:
        ``(rows sorted by period, mixed_flag)``.
    """
    counts = d["source"].value_counts()
    if not counts.empty and counts.iloc[0] >= 2:
        return d[d["source"] == counts.index[0]].sort_values("period"), False
    mixed = d.sort_values("period").drop_duplicates("period", keep="last")
    return mixed, mixed["source"].nunique() > 1


# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------


def submarket_bar_chart(latest: pd.DataFrame, title: str, unit_label: str, fmt: str) -> go.Figure | None:
    """Horizontal bars, one per submarket, sorted by value (magnitude comparison).

    Single series -> single colour and no legend; values are labelled at the
    bar end because the comparison *is* the message.
    """
    if latest.empty or len(latest) < 2:
        return None
    d = latest.sort_values("value")
    period = d["period"].max()
    sources = sorted(d["source"].unique())
    fig = go.Figure(
        go.Bar(
            x=d["value"], y=d["submarket"], orientation="h",
            marker={"color": SERIES[0], "cornerradius": 4},
            text=[fmt.format(v) for v in d["value"]], textposition="outside",
            textfont={"color": INK_SECONDARY}, cliponaxis=False,  # keep end labels visible
            customdata=d[["source", "period"]].values,
            hovertemplate="%{y}: " + fmt.replace("{:", "%{x:") + "<br>%{customdata[1]} · %{customdata[0]}<extra></extra>",
        )
    )
    # Explicit range from zero: Plotly.js autorange can under-size the axis when
    # it reserves space for outside text labels, which visually truncates bars.
    fig.update_xaxes(showgrid=True, range=[0, float(d["value"].max()) * 1.18],
                     title={"text": f"{unit_label} · source: {', '.join(sources)}"})
    fig = _style(fig, f"{title} ({period})", height=max(260, 46 * len(d) + 100))
    fig.update_layout(margin={"r": 80})  # room for the outside value labels
    return fig


def trend_chart(history: pd.DataFrame, title: str, y_title: str, submarkets: list[str] | None = None) -> go.Figure | None:
    """Lines over time, one per submarket (change over time).

    Args:
        history: Columns ``submarket, period, value`` (from ``MetricsStore.series``).
        submarkets: Which submarkets to draw (defaults to :data:`TREND_SUBMARKETS`).
    """
    if history is None or history.empty:
        return None
    submarkets = submarkets or TREND_SUBMARKETS
    fig = go.Figure()
    any_mixed = False
    for sm in submarkets:
        rows = history[history["submarket"] == sm]
        if rows.empty:
            continue
        d, mixed = pick_series(rows)
        if len(d) < 2:
            continue
        any_mixed |= mixed
        color = SUBMARKET_COLORS.get(sm, SERIES[-1])
        fig.add_trace(
            go.Scatter(
                x=d["period"], y=d["value"], name=sm + (" (mixed sources)" if mixed else ""),
                mode="lines+markers", customdata=d[["source"]].values,
                # Dashed = stitched from different brokers, i.e. not like-for-like.
                line={"color": color, "width": 2, "dash": "dash" if mixed else "solid"},
                marker={"size": 8, "color": color, "line": {"width": 2, "color": "#fcfcfb"}},
                hovertemplate=f"{sm}<br>%{{x}}: %{{y:,.4g}}<br>%{{customdata[0]}}<extra></extra>",
            )
        )
        # Direct label at the line end (identity is never colour-alone).
        fig.add_annotation(
            x=d["period"].iloc[-1], y=d["value"].iloc[-1], text=sm, showarrow=False,
            xanchor="left", xshift=8, font={"size": 11, "color": INK_SECONDARY},
        )
    if not fig.data:
        return None
    fig.update_layout(hovermode="x unified")
    fig.update_xaxes(type="category", categoryorder="category ascending")
    if any_mixed:
        title += " (dashed = mixed sources, not like-for-like)"
    fig = _style(fig, title, y_title)
    fig.update_layout(margin={"r": 110})  # room for end-of-line labels
    return fig


def take_up_chart(history: pd.DataFrame, avg: float | None) -> go.Figure | None:
    """Quarterly Central London take-up bars with the 10-year average as a reference line."""
    if history is None or history.empty:
        return None
    rows = history[history["submarket"] == "Central London"]
    if rows.empty:
        return None
    d, mixed = pick_series(rows)
    d = d.tail(10)
    fig = go.Figure(
        go.Bar(
            x=d["period"], y=d["value"] / 1e6, marker={"color": SERIES[0], "cornerradius": 4},
            customdata=d[["source"]].values, name="Take-up",
            hovertemplate="%{x}: %{y:.2f}m sq ft<br>%{customdata[0]}<extra></extra>",
        )
    )
    if avg:
        fig.add_hline(
            y=avg / 1e6, line={"color": INK_MUTED, "width": 1.5, "dash": "dash"},
            annotation_text=f"10-yr quarterly avg {avg / 1e6:.2f}m", annotation_position="bottom right",
            annotation_font={"color": INK_SECONDARY, "size": 11},
        )
    fig.update_xaxes(type="category")
    title = "Central London office take-up" + (" (bars from different sources)" if mixed else "")
    return _style(fig, title, "m sq ft")


def pipeline_chart(df: pd.DataFrame) -> go.Figure | None:
    """Stacked bars of the development pipeline by completion year: pre-let vs speculative."""
    if df.empty:
        return None
    pre = df[df["key"] == "pipeline_prelet_sqft"].groupby("period")["value"].sum()
    spec = df[df["key"] == "pipeline_speculative_sqft"].groupby("period")["value"].sum()
    years = sorted(set(pre.index) | set(spec.index))
    if not years:
        return None
    fig = go.Figure()
    for name, series, color in (("Pre-let", pre, SERIES[0]), ("Speculative (available)", spec, SERIES[1])):
        fig.add_trace(
            go.Bar(
                x=years, y=[series.get(y, 0) / 1e6 for y in years], name=name,
                marker={"color": color, "line": {"color": "#fcfcfb", "width": 2}},
                hovertemplate=f"{name}<br>%{{x}}: %{{y:.2f}}m sq ft<extra></extra>",
            )
        )
    fig.update_layout(barmode="stack")
    fig.update_xaxes(type="category")
    return _style(fig, "Central London development pipeline by completion year", "m sq ft")


def rates_chart(history: dict[str, pd.DataFrame]) -> go.Figure | None:
    """Bank Rate and 10-year gilt yield - same unit (%), so one axis is valid."""
    labels = {"bank_rate": "Bank Rate", "gilt_10y_yield": "10-yr gilt yield"}
    fig = go.Figure()
    for i, (key, label) in enumerate(labels.items()):
        d = history.get(key)
        if d is None or d.empty:
            continue
        d = d.sort_values("period")
        fig.add_trace(
            go.Scatter(
                x=d["period"], y=d["value"], name=label, mode="lines+markers",
                line={"color": SERIES[i], "width": 2, "shape": "hv" if key == "bank_rate" else "linear"},
                marker={"size": 8, "color": SERIES[i]},
                hovertemplate=f"{label}<br>%{{x}}: %{{y:.2f}}%<extra></extra>",
            )
        )
        fig.add_annotation(
            x=d["period"].iloc[-1], y=d["value"].iloc[-1], text=label, showarrow=False,
            xanchor="left", xshift=8, font={"size": 11, "color": INK_SECONDARY},
        )
    if not fig.data:
        return None
    fig.update_layout(hovermode="x unified")
    fig.update_xaxes(type="category")
    return _style(fig, "UK interest rates", "%")


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------


def build_charts(findings: list[SkillFinding], store=None) -> dict[str, go.Figure]:
    """Build every chart the available data supports.

    Args:
        findings: Validated findings from the current run (latest snapshot).
        store: Optional :class:`~cre_monitor.store.MetricsStore` for history
            (trend lines). Without it only snapshot charts are produced.

    Returns:
        Ordered mapping ``chart_id -> Figure`` (missing data -> chart omitted).
    """
    df = metrics_frame(findings)
    charts: dict[str, go.Figure | None] = {}

    rents = latest_by_submarket(df, "prime_rent")
    charts["prime_rent_by_submarket"] = submarket_bar_chart(rents, "Prime office rent by submarket", "£ psf pa", "£{:,.2f}")
    vac = latest_by_submarket(df, "vacancy_rate")
    charts["vacancy_by_submarket"] = submarket_bar_chart(vac, "Vacancy rate by submarket", "%", "{:.1f}%")

    if store is not None:
        charts["prime_rent_trend"] = trend_chart(store.series("prime_rent"), "Prime rent trend", "£ psf pa")
        charts["vacancy_trend"] = trend_chart(store.series("vacancy_rate"), "Vacancy rate trend", "%")
        avg_df = latest_by_submarket(df, "take_up_10y_avg_sqft")
        if avg_df.empty:
            hist_avg = store.series("take_up_10y_avg_sqft", "Central London")
            avg = float(hist_avg["value"].iloc[-1]) if not hist_avg.empty else None
        else:
            avg = float(avg_df["value"].iloc[0])
        charts["take_up"] = take_up_chart(store.series("take_up_sqft"), avg)
        charts["rates"] = rates_chart({k: store.series(k, "UK") for k in ("bank_rate", "gilt_10y_yield")})

    charts["pipeline"] = pipeline_chart(df)
    return {k: v for k, v in charts.items() if v is not None}
