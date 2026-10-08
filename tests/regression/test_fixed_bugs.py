"""Regression tests: each one reproduces a bug that was found and fixed, so it can't come back.

| Test | Bug it guards against |
|---|---|
| ``test_skill_conversation_is_append_only_with_one_tool_list`` | Live HTTP 400 "Invalid signature in thinking block": a separate structured-output call changed the tool list mid-conversation |
| ``test_same_day_briefs_keep_their_own_charts`` | A second brief on the same day overwrote the first brief's PNG charts |
| ``test_deltas_prefer_same_source_and_label_cross_source`` | "What changed" compared different brokers (BNP 8.4% -> Avison Young 6.3%) as if vacancy had fallen 2.1pp |
| ``test_deltas_never_compare_different_period_lengths`` | A half-year total followed by a quarterly one was reported as a halving; text ordering put 2026-H1 before 2026-Q1 |

Add a test here (with a row above) whenever you fix a bug that a test could have caught.
"""

from __future__ import annotations

from pathlib import Path

from cre_monitor.config import get_settings
from cre_monitor.graph.builder import run_brief
from cre_monitor.schemas import Metric, SkillFinding
from cre_monitor.store.metrics import MetricsStore


def _finding(*metrics: Metric) -> SkillFinding:
    return SkillFinding(skill="office-rents", headline="h", summary="s", metrics=list(metrics))


def test_skill_conversation_is_append_only_with_one_tool_list(fake_llm):
    """Live 400 'Invalid signature in thinking block ... tools list differs'.

    Every request in a skill must use the same tool list, and each request must
    extend the previous one (never edit or drop earlier messages).
    """
    run_brief(["macro-economy"])
    assert len(fake_llm.bound_tools) == 1 and fake_llm.bound_tools[0][-1] == "submit_finding"
    assert not any(k == "structured:SkillFinding" for k in fake_llm.kinds)   # no separate output call
    skill_calls = [c for c in fake_llm.calls if "SKILL INSTRUCTIONS" in str(c[0].content)]
    assert len(skill_calls) == 2
    for earlier, later in zip(skill_calls, skill_calls[1:]):
        assert later[: len(earlier)] == earlier                               # strictly append-only


def test_same_day_briefs_keep_their_own_charts(monkeypatch):
    """A second brief on the same day must not overwrite the first brief's PNG charts."""
    import cre_monitor.reporting.render as render

    def fake_export(figures, charts_dir, rel_prefix):  # no Chrome needed
        for cid in figures:
            (charts_dir / f"{cid}.png").write_bytes(b"png")
        return {cid: f"{rel_prefix}/{cid}.png" for cid in figures}

    monkeypatch.setattr(render, "export_pngs", fake_export)
    monkeypatch.setenv("REPORT_PNG", "1")
    get_settings.cache_clear()

    first, second = run_brief(), run_brief()
    for state in (first, second):
        md_path = Path(state["report_paths"]["markdown"])
        links = [line.split("](")[1].rstrip(")") for line in md_path.read_text(encoding="utf-8").splitlines()
                 if line.startswith("![")]
        assert links and all(f"charts/{state['run_id']}/" in link for link in links)
        assert all((md_path.parent / link).exists() for link in links)
    assert first["run_id"] != second["run_id"]


def test_deltas_prefer_same_source_and_label_cross_source(tmp_path):
    """Brokers define vacancy differently: compare a broker with its own history first."""
    store = MetricsStore(tmp_path / "m.sqlite")

    def vac(value, period, source):
        return Metric(key="vacancy_rate", submarket="Central London", value=value, unit="%", period=period,
                      source=source)

    store.record("old", [_finding(vac(8.4, "2026-Q1", "BNP"), vac(6.3, "2025-Q4", "Avison Young"))])

    # Avison Young has its own (older) history -> compare like with like, not with BNP's later Q1.
    (d,) = store.deltas([_finding(vac(6.3, "2026-Q2", "Avison Young"))], exclude_run_id="new")
    assert d.same_source and d.previous_source == "Avison Young" and d.previous_period == "2025-Q4"
    assert not d.is_material  # 6.3 -> 6.3

    # JLL has no history -> falls back to another source, clearly labelled.
    (d,) = store.deltas([_finding(vac(8.6, "2026-Q2", "JLL"))], exclude_run_id="new")
    assert not d.same_source
    assert "different sources: BNP -> JLL" in d.describe()


def test_deltas_never_compare_different_period_lengths(tmp_path):
    """A half-year total must not be compared with a quarterly one (it looked like a halving)."""
    store = MetricsStore(tmp_path / "m.sqlite")

    def investment(period, value):
        return _finding(Metric(key="investment_volume_gbp", submarket="Central London", value=value, unit="GBP",
                               period=period, source="JLL"))

    store.record("r1", [investment("2026-H1", 6e9)])
    assert store.deltas([investment("2026-Q3", 2e9)], exclude_run_id="r2") == []        # H vs Q: no "fall"
    store.record("r2", [investment("2026-Q2", 3e9)])
    (delta,) = store.deltas([investment("2026-Q3", 2e9)], exclude_run_id="r3")
    assert delta.previous_period == "2026-Q2"
