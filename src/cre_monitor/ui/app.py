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
  data-quality notes and charts relevant to the findings. The "📎 Reference
  earlier conversations" picker adds up to 3 past chats as dated background
  for the next question (see :func:`reference_picker`).
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
        history.append(assistant_turn(t.answer, t.skills, t.reasoning, t.issues, t.findings, t.refs, t.incident))
    st.session_state.thread_id = thread_id
    st.session_state.history = history
    st.query_params["thread"] = thread_id


def assistant_turn(answer, skills, reasoning, issues, findings, refs=None, incident=None) -> dict:
    """View model for one assistant message (used for live and reloaded turns alike)."""
    from cre_monitor.reporting.charts import build_charts
    from cre_monitor.store import get_conversation_store, get_store

    # Charts only for metrics present in this turn's findings (plus history trends for them).
    figs = list(build_charts(findings, get_store()).values()) if findings else []
    keys = {m.key for f in findings for m in f.metrics}
    figs = [f for f in figs if _figure_relevant(f, keys)][:4]
    store = get_conversation_store()
    ref_titles = [(c.title if (c := store.get(r)) else "(deleted conversation)") for r in refs or []]
    issues = issues or []
    if incident is not None:
        # Skill failures are explained by the incident panel; don't repeat raw errors as data notes.
        issues = [i for i in issues if not i.message.startswith("Skill failed:")]
    return {
        "id": uuid.uuid4().hex[:6], "role": "assistant", "content": answer,
        "skills": skills, "reasoning": reasoning, "issues": issues, "charts": figs,
        "ref_titles": ref_titles, "incident": incident,
    }


def render_incident(incident, where=st, compact: bool = False) -> None:
    """User-friendly error panel with a reference ID engineers can trace in the logs.

    Shows what happened in plain English, what the user can do, and the
    reference to quote (with a copy button). Raw technical details are tucked
    into a collapsed "for engineers" section.

    Args:
        incident: The :class:`~cre_monitor.errors.Incident` to show.
        where: Streamlit container to render into.
        compact: Narrow version for the sidebar (no columns or nested expander,
            which Streamlit doesn't allow inside the settings expander).
    """
    cat = incident.category
    total = incident.scope == "total"
    contact = get_settings().support_contact
    box = where.error if total else where.warning
    lead = "We couldn't answer this question." if total else "Part of the research failed - this answer may be incomplete."
    actions = "\n".join(f"- {a}" for a in cat.actions)
    box(
        f"**{cat.title}**\n\n{lead} {cat.message}\n\n**What you can do**\n{actions}",
        icon="🚫" if total else "⚠️",
    )
    if compact:
        where.caption(f"Reference for support - send to {contact}:")
        where.code(incident.id, language=None)
        return
    c1, c2 = where.columns([0.55, 0.45], vertical_alignment="center")
    c1.markdown(f"**Reference for support:** please send this ID to **{contact}** so they can trace the problem.")
    c2.code(incident.id, language=None)  # st.code has a built-in copy button
    details = where.expander("Technical details (for engineers)")
    details.markdown(
        f"- **Reference:** `{incident.id}` · **time:** {incident.created_at:%Y-%m-%d %H:%M:%S}\n"
        f"- **Category:** `{cat.code}` · **scope:** {incident.scope} · **retryable:** {'yes' if cat.retryable else 'no'}\n"
        f"- **Affected steps:** {', '.join(incident.affected)}\n"
        f"- **Conversation:** `{incident.thread_id or '-'}` · **run:** `{incident.run_id or '-'}`\n"
        f"- **Log file:** `{incident.log_file or 'not configured'}`  →  search for the reference ID"
    )
    details.code("\n".join(incident.details)[:4000], language=None)


# --------------------------------------------------------------------------
# Sidebar - conversations + settings
# --------------------------------------------------------------------------

def conversation_list() -> None:
    """New-chat button and the grouped, clickable conversation history."""
    from cre_monitor.graph.builder import delete_conversation
    from cre_monitor.store import get_conversation_store
    from cre_monitor.store.conversations import group_by_recency

    if st.sidebar.button("➕ New chat", width="stretch", key="new-chat"):
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
                c.title, key=f"open-{c.thread_id}", width="stretch",
                type="primary" if c.thread_id == current else "secondary",  # highlight the open one
                help=f"{c.turn_count} question(s) · last active {c.updated_at:%d %b %H:%M}",
            ):
                open_conversation(c.thread_id)
                st.rerun()
            with col_menu.popover("⋮", width="stretch"):
                new_title = st.text_input("Rename", value=c.title, key=f"title-{c.thread_id}")
                if st.button("Save name", key=f"rename-{c.thread_id}", width="stretch"):
                    store.rename(c.thread_id, new_title)
                    st.rerun()
                if st.button("🗑 Delete", key=f"delete-{c.thread_id}", width="stretch"):
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
        if st.button("Run full brief now", width="stretch", key="run-brief"):
            from cre_monitor.graph.builder import run_brief

            with st.status("Running all skills...", expanded=False) as status:
                try:
                    state = run_brief()
                except Exception as exc:  # noqa: BLE001 - show a reference, not a traceback
                    from cre_monitor.errors import incident_from_exception

                    state = {"incident": incident_from_exception(exc, step="brief")}
                incident = state.get("incident")
                if incident is not None and incident.scope == "total":
                    status.update(label="Brief failed", state="error")
                elif incident is not None:
                    status.update(label="Brief ready, with problems - see the Briefs tab", state="complete")
                else:
                    status.update(label="Brief ready - see the Briefs tab", state="complete")
            if incident is not None:
                render_incident(incident, compact=True)
            st.session_state.last_brief = state.get("report_paths", {}).get("html")


def sidebar() -> None:
    st.sidebar.title("London CRE Monitor")
    st.sidebar.caption("LangGraph agent PoC · Nan Fung Group London")
    if st.get_option("client.toolbarMode") == "developer":
        # Set by `cre-monitor ui --debug`, CRE_UI_DEBUG=1 or STREAMLIT_CLIENT_TOOLBAR_MODE=developer.
        st.sidebar.caption("🐞 Debug mode: developer toolbar (Rerun, Clear cache) enabled")
    conversation_list()
    st.sidebar.divider()
    settings_panel()


# --------------------------------------------------------------------------
# Chat tab
# --------------------------------------------------------------------------

def render_turn_details(turn: dict) -> None:
    """Supporting detail under an assistant answer."""
    if turn.get("incident") is not None:
        render_incident(turn["incident"])
    if turn.get("ref_titles"):
        st.caption("📎 Referenced: " + " · ".join(turn["ref_titles"]))
    if turn.get("skills"):
        st.caption(f"Skills used: {', '.join(turn['skills'])} - {turn.get('reasoning', '')}")
    if turn.get("charts"):
        cols = st.columns(min(2, len(turn["charts"])))
        for i, fig in enumerate(turn["charts"]):
            cols[i % len(cols)].plotly_chart(fig, key=f"{turn['id']}-{i}")
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

    refs = reference_picker()
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

            try:
                state = ask(question, thread_id=st.session_state.thread_id, stream_handler=on_update, refs=refs)
            except Exception as exc:  # noqa: BLE001 - never show users a raw traceback
                state = unexpected_failure(question, exc)
            incident = state.get("incident")
            if incident is None:
                status.update(label="Done", state="complete", expanded=False)
            elif incident.scope == "total":
                status.update(label="Could not complete the research", state="error", expanded=False)
            else:
                status.update(label="Done - with problems (see below)", state="complete", expanded=False)

        turn = assistant_turn(
            state.get("answer", ""), state.get("selected_skills"), state.get("planner_reasoning"),
            state.get("validation_issues"), state.get("findings") or [], state.get("context_refs"),
            incident,
        )
        st.markdown(turn["content"])
        render_turn_details(turn)
    st.session_state.history.append(turn)
    # Keep the conversation in the URL and refresh the sidebar so a brand-new chat
    # appears in the list (the sidebar was drawn before this turn ran).
    st.query_params["thread"] = st.session_state.thread_id
    st.rerun()


def unexpected_failure(question: str, exc: Exception) -> dict:
    """Handle an exception that escaped ``ask()`` entirely (e.g. a storage problem).

    Logs the traceback under a new incident reference and records the failed
    turn, so it stays visible in the conversation and can be traced later.
    """
    from cre_monitor.errors import incident_from_exception
    from cre_monitor.store import get_conversation_store

    thread_id = st.session_state.thread_id
    incident = incident_from_exception(exc, step="chat", thread_id=thread_id)
    answer = "I couldn't complete this request."
    try:
        get_conversation_store().record_turn(thread_id, question, answer, incident=incident)
    except Exception:  # noqa: BLE001 - the incident is already logged; don't fail twice
        pass
    return {"answer": answer, "incident": incident}


def reference_picker() -> list[str]:
    """Multiselect of earlier conversations to use as background for the next question.

    The selection is remembered per conversation (widget key includes the thread
    id) and stays until changed, so a run of follow-ups can keep the same context.
    The research skills never see referenced conversations; only the router and
    the answer step do, labelled as dated background.
    """
    from cre_monitor.store import get_conversation_store
    from cre_monitor.store.conversations import MAX_REFS

    current = st.session_state.thread_id
    others = {c.thread_id: c for c in get_conversation_store().list() if c.thread_id != current}
    if not others:
        return []
    key = f"refs-{current}"
    # Drop selections whose conversation was deleted since they were picked.
    if key in st.session_state:
        st.session_state[key] = [r for r in st.session_state[key] if r in others]
    return st.multiselect(
        "📎 Reference earlier conversations",
        options=list(others),
        format_func=lambda tid: f"{others[tid].title}  ·  {others[tid].updated_at:%d %b}",
        max_selections=MAX_REFS,
        key=key,
        placeholder=f"Optional: add up to {MAX_REFS} past chats as background",
        help="The answer can build on what was discussed there (dated, as background). "
             "Figures are always refreshed from current research.",
    )


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
    # st.iframe embeds a local HTML file as-is (scripts enabled, needed for the
    # interactive Plotly charts). That is safe here because the file is our own
    # generated report, whose template HTML-escapes all model/source text.
    st.iframe(path, height=1400)


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
        st.plotly_chart(fig)
    else:
        st.info("Not enough history for a trend line yet (needs 2+ periods).")
    with st.expander("Data table"):
        st.dataframe(series[series["submarket"].isin(chosen)] if chosen else series)


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------

def main() -> None:
    get_settings().ensure_dirs()
    from cre_monitor.logs import setup_logging

    setup_logging("ui")  # idempotent; incident details are written here for engineers
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
