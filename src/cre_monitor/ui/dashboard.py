"""Dashboard tab: tracked metrics, metric detail, and catalogue management.

Three sub-tabs:

* **📊 Overview** - a headline card per *tracked* metric (latest value, change
  versus the previous period from the same source), then the selected metric in
  detail: comparison across all submarkets, trend on a real date axis, source
  picker and the data behind the chart. Selection logic lives in
  :mod:`cre_monitor.reporting.dashboard` (unit-tested).
* **⚙️ Metrics** - choose which metrics are tracked, remove unwanted ones from
  the catalogue, and add new ones (with a feasibility check by Claude, see
  :func:`add_metric_panel`).
* **📍 Submarkets** - add places (with aliases), edit aliases/descriptions,
  remove places.

Catalogue edits are written to ``catalog/*.yaml`` (shared by every user of this
installation; commit them to git like any other change) with a version history
and edit-conflict check (:mod:`cre_monitor.catalog`).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from cre_monitor.catalog import MetricDef, get_catalog
from cre_monitor.reporting import dashboard as dash
from cre_monitor.ui.components import render_incident

AUTO_SOURCE = "Best available (automatic)"


def _store():
    from cre_monitor.store import get_store

    store = get_store()
    if store.is_empty():
        store.seed_from_fixture()
    return store


def _flash(kind: str, text: str) -> None:
    """Show a message on the next run (set just before st.rerun())."""
    st.session_state.dash_flash = (kind, text)


def _show_flash() -> None:
    if flash := st.session_state.pop("dash_flash", None):
        kind, text = flash
        {"error": st.error, "warning": st.warning}.get(kind, st.success)(text)


def _guarded(action, success: str) -> None:
    """Run a catalogue edit; report validation errors / conflicts instead of crashing."""
    from cre_monitor.versioned import ConflictError

    try:
        action()
    except (ValueError, ConflictError) as exc:
        _flash("error", str(exc))
    except Exception as exc:  # noqa: BLE001 - show a reference, not a traceback
        from cre_monitor.errors import incident_from_exception

        st.session_state.dash_incident = incident_from_exception(exc, step="catalogue")
    else:
        _flash("success", success)
    st.rerun()


# --------------------------------------------------------------------------
# Overview
# --------------------------------------------------------------------------

def overview(store) -> None:
    cat = get_catalog()
    tracked = cat.tracked()
    if not tracked:
        st.info("No metrics are tracked. Choose some in the **⚙️ Metrics** tab.")
        return
    st.caption("Latest figure for Central London (or the UK for economic series), with the change since the "
               "previous period **from the same source**. Hover a card for the definition.")
    data = {m.key: dash.prepare(store.series(m.key)) for m in tracked}
    for start in range(0, len(tracked), 4):
        cols = st.columns(4)
        for col, m in zip(cols, tracked[start:start + 4]):
            h = dash.headline(data[m.key])
            if h is None:
                col.metric(m.label, "No data yet", help=m.definition or None, border=True)
                continue
            delta = (f"{dash.format_change(h.value, h.previous, m.unit)} vs {h.previous_period}"
                     if h.previous is not None else None)
            col.metric(m.label, dash.format_value(h.value, m.unit), delta=delta, delta_color="off",
                       help=m.definition or None, border=True)
            col.caption(f"{h.place} · {h.period} · {h.source}")

    st.divider()
    labels = {m.key: f"{m.label}  ·  {m.group}" for m in tracked}
    key = st.selectbox("Explore a metric", list(labels), format_func=labels.get, key="dash-metric")
    metric_detail(store, cat.metric(key))


def metric_detail(store, m: MetricDef) -> None:
    from cre_monitor.catalog import skills_using_metric

    raw = store.series(m.key)
    df = dash.prepare(raw)
    collectors = skills_using_metric(m.key)
    st.caption(f"**Definition:** {m.definition or '–'}  \n**Unit:** {m.unit} · **Collected by:** "
               f"{', '.join(collectors) if collectors else 'no skill yet'}")
    if df.empty:
        st.info("No figures recorded yet. They appear after a brief (or a chat question) that runs "
                + (f"**{', '.join(collectors)}**." if collectors else "a skill collecting this metric."))
        return

    order = {p: i for i, p in enumerate(get_catalog().all_places())}
    places = sorted(df["submarket"].unique(), key=lambda p: (order.get(p, len(order)), p))
    c1, c2 = st.columns([1, 2])
    src_choice = c1.selectbox("Source", [AUTO_SOURCE, *dash.sources_by_coverage(df)], key=f"dash-src-{m.key}",
                              help="Brokers define metrics differently. Automatic = for each submarket, "
                                   "the source with the most data.")
    source = None if src_choice == AUTO_SOURCE else src_choice
    chosen = c2.multiselect("Submarkets", places, default=places, key=f"dash-places-{m.key}",
                            help="All submarkets with data are shown. Up to 4 share one trend chart; "
                                 "more are drawn as one small panel each.")
    if not chosen:
        st.info("Pick at least one submarket.")
        return
    d = df[df["submarket"].isin(chosen)]

    latest = dash.latest_by_place(d, source)
    if (fig := dash.snapshot_chart(latest, m)) is not None:
        st.plotly_chart(fig, key=f"snap-{m.key}")
    elif len(latest) == 1:
        row = latest.iloc[0]
        st.metric(f"{m.label} - {row['submarket']}", dash.format_value(row["value"], m.unit),
                  help=f"{row['period']} · {row['source']}")

    fig, lines = dash.trend_figure(d, chosen, m, source)
    if fig is not None:
        st.plotly_chart(fig, key=f"trend-{m.key}")
        notes = [f"**{ln.place}**: {ln.source}, {dash.freq_name(ln.freq)}, {len(ln.rows)} points"
                 + (f" ({ln.left_out} other figures not drawn)" if ln.left_out else "") for ln in lines]
        st.caption(" · ".join(notes))
    else:
        st.info("Not enough history for a trend yet: a line needs 2+ periods from one source. "
                "The bars above show the latest figures; history grows with every brief.")
    if skipped := len(raw) - len(df):
        st.caption(f"{skipped} figure(s) have a period label that can't be placed on a timeline; "
                   "they are listed in the data table only.")

    with st.expander("How to read this"):
        st.markdown(
            "- **Each line follows one source** (broker), because brokers define metrics differently. "
            "Choose a source above, or leave it on automatic (the source with the most data per submarket).\n"
            "- **One period length per line**: quarterly figures are never joined to half-year or annual ones.\n"
            "- **Dashed line** = no single source had 2+ points, so periods from different sources were "
            "stitched together. Treat the movement with caution.\n"
            "- The **time axis is real time**: a gap between points means periods with no recorded figure.\n"
            "- **Bars** compare the latest period per submarket, from one consistent source where possible.\n"
            "- Figures come from the research skills (broker reports, news) and, for economic series, "
            "directly from the Bank of England / ONS. Every figure passed the validator's plausibility checks.")

    with st.expander("Data table"):
        show_all = st.toggle("Show all sources and periods (not only what is drawn)", key=f"dash-all-{m.key}")
        table = raw[raw["submarket"].isin(chosen)] if show_all else (
            pd.concat([ln.rows for ln in lines]) if lines else latest)
        view = table[["submarket", "period", "value", "source"]].copy()
        view["value"] = [dash.format_value(v, m.unit) for v in view["value"]]
        st.dataframe(view, hide_index=True, width="stretch")


# --------------------------------------------------------------------------
# Metrics management
# --------------------------------------------------------------------------

def metrics_manager(store) -> None:
    from cre_monitor.catalog import remove_metric, set_tracked, skills_using_metric

    cat = get_catalog()
    counts = store.frame().groupby("key").size().to_dict() if not store.is_empty() else {}
    st.caption("Ticked metrics appear in the Overview. Unticking only hides a metric - its history is kept. "
               "🔒 = used by the report or data tools, can't be removed. Changes are saved to "
               "`catalog/metrics.yaml` for everyone using this installation.")
    for group in cat.groups():
        members = [m for m in cat.metrics if m.group == group]
        n_tracked = sum(m.tracked for m in members)
        with st.expander(f"{group} ({n_tracked} of {len(members)} tracked)", expanded=False):
            for m in members:
                c_track, c_info, c_del = st.columns([0.07, 0.83, 0.10], vertical_alignment="center")
                ticked = c_track.checkbox("Track", value=m.tracked, key=f"track-{m.key}",
                                          label_visibility="collapsed", help=f"Show {m.label} in the Overview")
                if ticked != m.tracked:
                    _guarded(lambda m=m, t=ticked: set_tracked(m.key, t, expected_version=cat.version),
                             f"{m.label} {'is now tracked' if ticked else 'is no longer tracked'}.")
                users = skills_using_metric(m.key)
                c_info.markdown(
                    f"**{m.label}** ({m.unit}){' 🔒' if m.protected else ''}  \n"
                    f"<small>{m.definition or ''}<br>`{m.key}` · {counts.get(m.key, 0)} figures recorded · "
                    f"collected by: {', '.join(users) or 'no skill'}</small>", unsafe_allow_html=True)
                if not m.protected:
                    with c_del.popover("🗑", help="Remove from the catalogue"):
                        st.markdown(f"Remove **{m.label}** from the catalogue?")
                        st.caption("Recorded figures stay in the database. " + (
                            f"It is still collected by {', '.join(users)}: it will also be removed from "
                            "those skills' metric lists." if users else ""))
                        if st.button("Remove", type="primary", key=f"rm-metric-{m.key}"):
                            def _remove(m=m, users=users):
                                if users:
                                    from cre_monitor.skills.editor import detach_metric

                                    detach_metric(m.key)
                                remove_metric(m.key)
                            _guarded(_remove, f"Removed {m.label} from the catalogue.")
    st.divider()
    add_metric_panel()


def add_metric_panel() -> None:
    """Placeholder until the add-metric assessment is wired in (see metrics_admin)."""
    from cre_monitor.ui.add_metric import add_metric_panel as panel

    panel()


# --------------------------------------------------------------------------
# Submarkets management
# --------------------------------------------------------------------------

def submarkets_manager(store) -> None:
    from cre_monitor.catalog import SubmarketDef, add_submarket, remove_submarket, update_submarket

    cat = get_catalog()
    counts = store.frame().groupby("submarket").size().to_dict() if not store.is_empty() else {}
    st.caption("The places figures are recorded against. Research skills are told to use these names, and "
               "**aliases** (other spellings brokers use) are converted automatically - e.g. Docklands → "
               "Canary Wharf. 🔒 = used by the report, can't be removed. Saved to `catalog/submarkets.yaml`.")
    for s in cat.submarkets:
        c_info, c_edit, c_del = st.columns([0.8, 0.1, 0.1], vertical_alignment="center")
        kind = " · economic series" if s.kind == "macro" else ""
        c_info.markdown(
            f"**{s.name}**{' 🔒' if s.protected else ''}{kind}  \n<small>{s.description or ''}<br>"
            f"Aliases: {', '.join(s.aliases) or '–'} · {counts.get(s.name, 0)} figures recorded</small>",
            unsafe_allow_html=True)
        with c_edit.popover("✏️", help=f"Edit {s.name}"):
            aliases = st.text_input("Aliases (comma-separated)", ", ".join(s.aliases), key=f"alias-{s.name}")
            desc = st.text_input("Description", s.description, key=f"desc-{s.name}")
            if st.button("Save", key=f"save-sm-{s.name}", type="primary"):
                _guarded(lambda s=s, a=aliases, d=desc: update_submarket(
                    s.name, aliases=[x.strip() for x in a.split(",")], description=d,
                    expected_version=cat.version), f"Saved {s.name}.")
        if not s.protected:
            with c_del.popover("🗑", help=f"Remove {s.name}"):
                st.markdown(f"Remove **{s.name}**?")
                st.caption("Skills stop using this name. Figures already recorded stay in the database.")
                if st.button("Remove", type="primary", key=f"rm-sm-{s.name}"):
                    _guarded(lambda s=s: remove_submarket(s.name, expected_version=cat.version),
                             f"Removed {s.name}.")

    st.divider()
    st.markdown("**➕ Add a submarket**")
    with st.form("add-submarket", clear_on_submit=True):
        name = st.text_input("Name", placeholder="e.g. Victoria")
        aliases = st.text_input("Aliases (optional, comma-separated)", placeholder="e.g. Victoria & Westminster, SW1")
        desc = st.text_input("Description (optional)", placeholder="Which area it covers")
        kind = st.radio("Type", ["Office submarket", "Economic geography (for economic series)"], horizontal=True)
        if st.form_submit_button("Add submarket", type="primary"):
            if not name.strip():
                _flash("error", "Please enter a name.")
                st.rerun()
            _guarded(lambda: add_submarket(SubmarketDef(
                name=name, aliases=[a.strip() for a in aliases.split(",")], description=desc,
                kind="submarket" if kind.startswith("Office") else "macro"), expected_version=cat.version),
                f"Added {name.strip()}. Skills will use it from the next run.")


# --------------------------------------------------------------------------
# Tab
# --------------------------------------------------------------------------

def dashboard_tab() -> None:
    store = _store()
    _show_flash()
    if incident := st.session_state.pop("dash_incident", None):
        render_incident(incident)
    t_over, t_metrics, t_places = st.tabs(["📊 Overview", "⚙️ Metrics", "📍 Submarkets"])
    with t_over:
        overview(store)
    with t_metrics:
        metrics_manager(store)
    with t_places:
        submarkets_manager(store)
