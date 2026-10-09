"""Streamlit building blocks shared by the UI modules (app, dashboard, skills tab).

Kept out of ``app.py`` because Streamlit runs that file as a script: importing
it from another module would execute the whole app again.
"""

from __future__ import annotations

import html

import streamlit as st

from cre_monitor.config import get_settings


def esc(text: str | None) -> str:
    """HTML-escape user-editable text before it goes into ``st.markdown(..., unsafe_allow_html=True)``.

    Catalogue entries, skill text and file names can be edited by anyone using the UI (or
    proposed by Claude); unescaped, they could inject HTML into other users' pages.
    """
    return html.escape(text or "")


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
