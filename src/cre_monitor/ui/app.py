"""Streamlit front-end: chat with the agent, browse briefs, explore metrics.

Run with ``cre-monitor ui`` or ``streamlit run src/cre_monitor/ui/app.py``.

Sidebar:
* **New chat** and the **conversation list** (grouped Today / Yesterday /
  Previous 7 days / Older). Click a conversation to reopen it and keep asking:
  the agent resumes with the earlier messages as context. The "⋮" menu renames
  or deletes a conversation. The open conversation is also in the page URL
  (``?thread=<id>``), so a refresh or bookmark reopens it.
* **Settings** (offline/demo toggles) and **Run full brief now**.

Tabs:
* **Chat**      - multi-turn Q&A. Each turn streams graph progress (planner ->
  skills -> validator -> answer), then shows the answer, the skills used,
  data-quality notes and charts relevant to the findings.
* **Briefs**    - view/download previously generated market briefs.
* **Dashboard** - interactive time series from the metrics store.

Where conversations live: the agent's memory per thread is in LangGraph's
checkpointer (``data/checkpoints.sqlite``); titles and per-turn details for
listing/redrawing are in ``data/conversations.sqlite`` (see
:mod:`cre_monitor.store.conversations`).

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
# Conversation state helpers
# --------------------------------------------------------------------------

def start_new_chat() -> None:
    """Switch to a fresh, empty conversation (it appears in the list after its first question)."""
    from cre_monitor.graph.builder import new_thread_id

    st.session_state.thread_id = new_thread_id()
    st.session_state.history = []
    st.query_params.clear()


def open_conversation(thread_id: str) -> None:
    """Load a saved conversation into the chat view; new questions continue it."""
    from cre_monitor.store import get_conversation_store

    history: list[dict] = []
    for t in get_conversation_store().turns(thread_id):
        history.append({"role": "user", "content": t.question})
        history.append(assistant_turn(t.answer, t.skills, t.reasoning, t.issues, t.findings))
    st.session_state.thread_id = thread_id
    st.session_state.history = history
    st.query_params["thread"] = thread_id


def assistant_turn(answer, skills, reasoning, issues, findings) -> dict:
    """View model for one assistant message (used for live and reloaded turns alike)."""
    from cre_monitor.reporting.charts import build_charts
    from cre_monitor.store import get_store

    # Charts only for metrics present in this turn's findings (plus history trends for them).
    figs = list(build_charts(findings, get_store()).values()) if findings else []
    keys = {m.key for f in findings for m in f.metrics}
    figs = [f for f in figs if _figure_relevant(f, keys)][:4]
    return {
        "id": uuid.uuid4().hex[:6], "role": "assistant", "content": answer,
        "skills": skills, "reasoning": reasoning, "issues": issues or [], "charts": figs,
    }


# --------------------------------------------------------------------------
# Sidebar - conversations + settings
# --------------------------------------------------------------------------

def conversation_list() -> None:
    """New-chat button and the grouped, clickable conversation history."""
    from cre_monitor.graph.builder import delete_conversation
    from cre_monitor.store import get_conversation_store
    from cre_monitor.store.conversations import group_by_recency

    if st.sidebar.button("➕ New chat", use_container_width=True, key="new-chat"):
        start_new_chat()
        st.rerun()

    store = get_conversation_store()
    conversations = store.list()
    if not conversations:
        st.sidebar.caption("No conversations yet. Ask a question to start one.")
        return

    current = st.session_state.thread_id
    for label, items in group_by_recency(conversations):
        st.sidebar.caption(label)
        for c in items:
            col_open, col_menu = st.sidebar.columns([0.84, 0.16], vertical_alignment="center")
            if col_open.button(
                c.title, key=f"open-{c.thread_id}", use_container_width=True,
                type="primary" if c.thread_id == current else "secondary",  # highlight the open one
                help=f"{c.turn_count} question(s) · last active {c.updated_at:%d %b %H:%M}",
            ):
                open_conversation(c.thread_id)
                st.rerun()
            with col_menu.popover("⋮", use_container_width=True):
                new_title = st.text_input("Rename", value=c.title, key=f"title-{c.thread_id}")
                if st.button("Save name", key=f"rename-{c.thread_id}", use_container_width=True):
                    store.rename(c.thread_id, new_title)
                    st.rerun()
                if st.button("🗑 Delete", key=f"delete-{c.thread_id}", use_container_width=True):
                    delete_conversation(c.thread_id)
                    if c.thread_id == current:
                        start_new_chat()
                    st.rerun()


def settings_panel() -> None:
    """Run-mode toggles, model info and the manual brief trigger."""
    s = get_settings()
    with st.sidebar.expander("⚙️ Settings & brief", expanded=False):
        offline = st.toggle("Offline data (fixtures)", value=s.cre_offline,
                            help="Use canned data instead of live web/API calls.")
        demo_allowed = bool(s.anthropic_api_key)
        demo = st.toggle("Demo mode (no LLM)", value=bool(s.cre_demo_mode), disabled=not demo_allowed,
                         help="Without ANTHROPIC_API_KEY demo mode is always on.")
        # Apply toggles by updating env vars and rebuilding the settings singleton.
        if offline != s.cre_offline or (demo_allowed and demo != s.cre_demo_mode):
            os.environ["CRE_OFFLINE"] = "1" if offline else "0"
            os.environ["CRE_DEMO_MODE"] = "1" if demo else "0"
            get_settings.cache_clear()
            st.rerun()
        st.markdown(
            f"**LLM:** {'demo (canned findings)' if s.cre_demo_mode else s.model_synthesis}  \n"
            f"**Data:** {'offline fixtures' if s.cre_offline else ('Tavily + public APIs' if s.tavily_api_key else 'Google News + public APIs')}"
        )
        if st.button("Run full brief now", use_container_width=True, key="run-brief"):
            from cre_monitor.graph.builder import run_brief

            with st.status("Running all skills...", expanded=False) as status:
                state = run_brief()
                status.update(label="Brief ready - see the Briefs tab", state="complete")
            st.session_state.last_brief = state.get("report_paths", {}).get("html")


def sidebar() -> None:
    st.sidebar.title("London CRE Monitor")
    st.sidebar.caption("LangGraph agent PoC · Nan Fung Group London")
    conversation_list()
    st.sidebar.divider()
    settings_panel()


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
    from cre_monitor.store import get_conversation_store

    current = get_conversation_store().get(st.session_state.thread_id)
    st.caption(f"💬 {current.title}" if current else "💬 New chat")

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

        turn = assistant_turn(
            state.get("answer", ""), state.get("selected_skills"), state.get("planner_reasoning"),
            state.get("validation_issues"), state.get("findings") or [],
        )
        st.markdown(turn["content"])
        render_turn_details(turn)
    st.session_state.history.append(turn)
    # Keep the conversation in the URL and refresh the sidebar so a brand-new chat
    # appears in the list (the sidebar was drawn before this turn ran).
    st.query_params["thread"] = st.session_state.thread_id
    st.rerun()


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
    get_settings().ensure_dirs()
    if "thread_id" not in st.session_state:
        # First load of this browser session: reopen the conversation named in the
        # URL (refresh / bookmark), otherwise start a new chat.
        from cre_monitor.store import get_conversation_store

        requested = st.query_params.get("thread")
        if requested and get_conversation_store().get(requested):
            open_conversation(requested)
        else:
            start_new_chat()
    sidebar()
    chat, briefs, dash = st.tabs(["💬 Chat", "📄 Briefs", "📈 Dashboard"])
    with chat:
        chat_tab()
    with briefs:
        briefs_tab()
    with dash:
        dashboard_tab()


main()
