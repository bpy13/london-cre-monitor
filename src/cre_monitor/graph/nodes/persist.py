"""Persist node: save validated metrics and compute period-on-period deltas.

Runs after validation so that only plausible numbers enter the long-term
history. On the very first run the store is seeded with historical
quarterly figures (``fixtures/history.json``) so trends and "what changed"
are meaningful immediately.
"""

from __future__ import annotations

import logging

from cre_monitor.graph.state import AgentState
from cre_monitor.store import get_store

logger = logging.getLogger(__name__)


def persist(state: AgentState) -> dict:
    """Graph node."""
    store = get_store()
    if store.is_empty():
        store.seed_from_fixture()
    findings = [f for f in state.get("findings") or [] if not f.error]
    run_id = state["run_id"]
    # Compute deltas BEFORE recording, against everything stored so far.
    deltas = store.deltas(findings, exclude_run_id=run_id)
    n = store.record(run_id, findings)
    logger.info("Persisted %d metrics; %d deltas vs earlier periods", n, len(deltas))
    return {"deltas": deltas}


def route_after_persist(state: AgentState) -> str:
    """Brief mode -> synthesis/report; chat mode -> conversational answer."""
    return "synthesis" if state.get("mode") == "brief" else "chat_answer"
