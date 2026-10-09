"""Performance-check answer keys (signals, moderation, storage) and run planning."""

from __future__ import annotations

import pytest

from cre_monitor.benchmark import answer_key as ak, runner
from cre_monitor.benchmark.answer_key import AnswerKey
from cre_monitor.style import save_example, set_roles
from tests.support.samples import AY_URL, REPORT, key_entry


def test_signals_safe_entries_and_storage():
    key = AnswerKey(report="r.md", entries=[
        key_entry(), key_entry(key="vacancy_rate", value=9.9, unit="%"),                   # not in the document
        key_entry(key="prime_rent", submarket="Mayfair", value=190, unit="GBP psf pa"),  # unknown place
        key_entry(key="vacancy_rate", value=6.3, unit="%", period="last quarter"),       # unparseable period
        key_entry(key="vacancy_rate", value=6.3, unit="%", source="JLL", confidence=0.5),  # low confidence
    ])
    ak.compute_signals(key, REPORT)
    safe = [e.safe for e in key.entries]
    assert safe == [True, False, False, False, False]
    assert key.entries[1].catalogue_match and not key.entries[1].in_document
    assert not key.entries[2].catalogue_match and not key.entries[3].period_ok
    assert len({e.id for e in key.entries}) == 5                          # stable ids
    assert key.accept_safe() == 1 and key.stats()["accepted"] == 1
    ak.save_key(key)
    assert ak.load_key("r.md") == key


def test_plan_groups_by_skill_and_task_never_reveals_values():
    from cre_monitor.catalog import MetricDef, add_metric

    add_metric(MetricDef(key="average_lease_length", label="Average lease length", unit="years"))
    key = AnswerKey(report="r.md", period="2026-Q2", publisher="Avison Young", entries=[
        key_entry(status="accepted"), key_entry(key="vacancy_rate", value=6.3, unit="%", status="accepted"),
        key_entry(key="average_lease_length", value=7.0, unit="years", status="accepted"),
        key_entry(key="prime_yield", value=5.25, unit="%", status="rejected")])
    plan = runner.plan_run(key)
    assert list(plan.groups) == ["submarket-dynamics"]                     # one skill covers both
    assert [e.key for e in plan.not_collectable] == ["average_lease_length"]
    assert plan.estimate_usd > 0
    task = runner.benchmark_task(plan.groups["submarket-dynamics"], "2026-Q2", hints=True, publisher="Avison Young")
    assert "period 2026-Q2" in task and "Avison Young" in task and AY_URL in task
    assert "2600000" not in task and "6.3" not in task                     # never the answers
    assert AY_URL not in runner.benchmark_task(plan.groups["submarket-dynamics"], "2026-Q2", hints=False)


def _benchmark_report(with_key: bool = True) -> ak.AnswerKey | None:
    save_example("ref.md", REPORT.encode())
    set_roles("ref.md", benchmark=True)
    if not with_key:
        return None
    key = ak.AnswerKey(report="ref.md", period="2026-Q2", publisher="Avison Young", themes=["Take-up steady"],
                       entries=[key_entry(), key_entry(key="vacancy_rate", value=9.9, unit="%")])  # 2nd: not in report
    ak.compute_signals(key, REPORT)
    ak.save_key(key)
    return key


def test_apply_edits_changes_status_value_and_rechecks_signals():

    key = _benchmark_report()
    bad = next(e for e in key.entries if not e.in_document)
    n = ak.apply_edits(key, [{"id": bad.id, "value": 6.3, "status": "accepted"}], REPORT)
    assert n == 1 and bad.in_document and bad.status == "accepted"            # corrected value is in the report
    with pytest.raises(ValueError, match="Unknown status"):
        ak.apply_edits(key, [{"id": bad.id, "status": "maybe"}], REPORT)
