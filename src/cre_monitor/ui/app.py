"""Streamlit front-end: chat with the agent, browse briefs, explore metrics.

Run with ``cre-monitor ui`` or ``streamlit run src/cre_monitor/ui/app.py``.

Tabs:
* **Chat**      - multi-turn Q&A. Each turn streams graph progress (planner ->
  skills -> validator -> answer), then shows the answer, the skills used,
  data-quality notes and charts relevant to the findings.
* **Briefs**    - view/download previously generated market briefs.
* **Dashboard** - interactive time series from the metrics store.

Streamlit re-runs this script top to bottom on every interaction; anything
that must survive a re-run lives in ``st.session_state``.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from cre_monitor.config import get_settings

st.set_page_config(page_title="London CRE Monitor", page_icon="🏢", layout="wide")

#: Friendly labels for graph nodes shown in the progress panel.
NODE_LABELS = {
    "planner": "Planning which skills to use",
    "skill_runner": "Skill finished",
    "validator": "Validating data quality",
    "persist": "Saving metrics & comparing with history",
    "chat_answer": "Writing the answer",
    "synthesis": "Synthesising the executive summary",
    "report_writer": "Rendering the report",
}


# --------------------------------------------------------------------------
# Sidebar - run settings
# --------------------------------------------------------------------------

def sidebar() -> None:
    s = get_settings()
    st.sidebar.title("London CRE Monitor")
    st.sidebar.caption("LangGraph agent PoC · Nan Fung Group London")

    offline = st.sidebar.toggle("Offline data (fixtures)", value=s.cre_offline,
                                help="Use canned data instead of live web/API calls.")
    demo_allowed = bool(s.anthropic_api_key)
    demo = st.sidebar.toggle("Demo mode (no LLM)", value=bool(s.cre_demo_mode), disabled=not demo_allowed,
                             help="Without ANTHROPIC_API_KEY demo mode is always on.")
    # Apply toggles by updating env vars and rebuilding the settings singleton.
    if offline != s.cre_offline or (demo_allowed and demo != s.cre_demo_mode):
        os.environ["CRE_OFFLINE"] = "1" if offline else "0"
        os.environ["CRE_DEMO_MODE"] = "1" if demo else "0"
        get_settings.cache_clear()
        st.rerun()

    s = get_settings()
    st.sidebar.markdown(
        f"**LLM:** {'demo (canned findings)' if s.cre_demo_mode else s.model_synthesis}  \n"
        f"**Data:** {'offline fixtures' if s.cre_offline else ('Tavily + public APIs' if s.tavily_api_key else 'Google News + public APIs')}"
    )

    st.sidebar.divider()
    if st.sidebar.button("New conversation", use_container_width=True):
        st.session_state.thread_id = uuid.uuid4().hex[:8]
        st.session_state.history = []
        st.rerun()
    st.sidebar.caption(f"Thread: `{st.session_state.thread_id}`")

    st.sidebar.divider()
    if st.sidebar.button("Run full brief now", type="primary", use_container_width=True):
        from cre_monitor.graph.builder import run_brief

        with st.sidebar.status("Running all skills...", expanded=False) as status:
            state = run_brief()
            status.update(label="Brief ready - see the Briefs tab", state="complete")
        st.session_state.last_brief = state.get("report_paths", {}).get("html")


# --------------------------------------------------------------------------
# Chat tab
# --------------------------------------------------------------------------

def render_turn_details(turn: dict) -> None:
    """Supporting detail under an assistant answer."""
    if turn.get("skills"):
        st.caption(f"Skills used: {', '.join(turn['skills'])} - {turn.get('reasoning', '')}")
    if turn.get("charts"):
        cols = st.columns(min(2, len(turn["charts"])))
        for i, fig in enumerate(turn["charts"]):
            cols[i % len(cols)].plotly_chart(fig, use_container_width=True, key=f"{turn['id']}-{i}")
    if turn.get("issues"):
        with st.expander(f"Data-quality notes ({len(turn['issues'])})"):
            for issue in turn["issues"]:
                st.markdown(f"- **{issue.level}** ({issue.skill}): {issue.message}")


def chat_tab() -> None:
    for turn in st.session_state.history:
        with st.chat_message(turn["role"]):
            st.markdown(turn["content"])
            if turn["role"] == "assistant":
                render_turn_details(turn)

    if not st.session_state.history:
        st.info(
            "Try: *What are prime rents in the West End vs the City?* · "
            "*How is Canary Wharf vacancy trending?* · *What's in the development pipeline for 2027?* · "
            "*How do interest rates affect London office values right now?* · *Any major news this month?*"
        )

    question = st.chat_input("Ask about the London office market...")
    if not question:
        return
    st.session_state.history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    from cre_monitor.graph.builder import ask
    from cre_monitor.reporting.charts import build_charts
    from cre_monitor.store import get_store

    with st.chat_message("assistant"):
        with st.status("Researching...", expanded=True) as status:
            def on_update(node: str, update: dict) -> None:
                label = NODE_LABELS.get(node, node)
                if node == "planner" and update:
                    label += f": {', '.join(update.get('selected_skills') or ['none'])}"
                if node == "skill_runner" and update:
                    label += f": {update['findings'][0].skill}"
                status.write(label)

            state = ask(question, thread_id=st.session_state.thread_id, stream_handler=on_update)
            status.update(label="Done", state="complete", expanded=False)

        answer = state.get("answer", "")
        findings = state.get("findings") or []
        # Charts only for data present in this turn's findings (plus history trends for those metrics).
        figs = list(build_charts(findings, get_store()).values()) if findings else []
        keys = {m.key for f in findings for m in f.metrics}
        figs = [f for f in figs if _figure_relevant(f, keys)][:4]
        turn = {
            "id": uuid.uuid4().hex[:6], "role": "assistant", "content": answer,
            "skills": state.get("selected_skills"), "reasoning": state.get("planner_reasoning"),
            "issues": state.get("validation_issues") or [], "charts": figs,
        }
        st.markdown(answer)
        render_turn_details(turn)
    st.session_state.history.append(turn)


def _figure_relevant(fig, keys: set[str]) -> bool:
    """Keep a chart only if its subject matches a metric returned this turn."""
    title = (fig.layout.title.text or "").lower()
    rules = {
        "rent": "prime_rent", "vacancy": "vacancy_rate", "take-up": "take_up_sqft",
        "pipeline": "pipeline_prelet_sqft", "interest rates": "bank_rate",
    }
    return any(phrase in title and key in keys for phrase, key in rules.items())


# --------------------------------------------------------------------------
# Briefs tab
# --------------------------------------------------------------------------

def briefs_tab() -> None:
    reports = sorted(get_settings().reports_dir.glob("*/brief_*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not reports:
        st.info("No briefs yet. Click **Run full brief now** in the sidebar, or run `cre-monitor brief`.")
        return
    labels = {f"{p.parent.name} · {p.stem.removeprefix('brief_')}": p for p in reports}
    choice = st.selectbox("Brief", list(labels))
    path: Path = labels[choice]
    md_path = path.with_suffix(".md")
    c1, c2 = st.columns(2)
    c1.download_button("Download HTML", path.read_bytes(), file_name=path.name, mime="text/html")
    if md_path.exists():
        c2.download_button("Download Markdown", md_path.read_bytes(), file_name=md_path.name, mime="text/markdown")
    components.html(path.read_text(encoding="utf-8"), height=1400, scrolling=True)


# --------------------------------------------------------------------------
# Dashboard tab
# --------------------------------------------------------------------------

def dashboard_tab() -> None:
    from cre_monitor.reporting.charts import TREND_SUBMARKETS, trend_chart
    from cre_monitor.schemas import METRIC_KEYS
    from cre_monitor.store import get_store

    store = get_store()
    if store.is_empty():
        store.seed_from_fixture()
    df = store.frame()
    keys = [k for k in METRIC_KEYS if k in set(df["key"])]
    c1, c2 = st.columns([1, 2])
    key = c1.selectbox("Metric", keys, index=keys.index("prime_rent") if "prime_rent" in keys else 0,
                       format_func=lambda k: k.replace("_", " "))
    series = store.series(key)
    available = sorted(series["submarket"].unique())
    default = [s for s in TREND_SUBMARKETS if s in available] or available[:4]
    chosen = c2.multiselect("Submarkets (max 4 for readability)", available, default=default, max_selections=4)
    fig = trend_chart(series, key.replace("_", " ").capitalize(), METRIC_KEYS.get(key, ""), chosen)
    if fig is not None:
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Not enough history for a trend line yet (needs 2+ periods).")
    with st.expander("Data table"):
        st.dataframe(series[series["submarket"].isin(chosen)] if chosen else series, use_container_width=True)


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------

def main() -> None:
    st.session_state.setdefault("thread_id", uuid.uuid4().hex[:8])
    st.session_state.setdefault("history", [])
    get_settings().ensure_dirs()
    sidebar()
    chat, briefs, dash = st.tabs(["💬 Chat", "📄 Briefs", "📈 Dashboard"])
    with chat:
        chat_tab()
    with briefs:
        briefs_tab()
    with dash:
        dashboard_tab()


main()
