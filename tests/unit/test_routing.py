"""Keyword routing (fallback router)."""

from __future__ import annotations

from cre_monitor.graph.nodes.planner import keyword_route


def test_keyword_routing():
    assert keyword_route("What is the prime rent in Mayfair?")[0] == "office-rents"
    assert "macro-economy" in keyword_route("Will the Bank of England cut interest rates?")
    assert "supply-pipeline" in keyword_route("How much speculative development completes in 2027?")
