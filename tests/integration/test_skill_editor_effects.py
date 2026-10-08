"""Skill editor saves, deletes and metric links - and their effect on the registry."""

from __future__ import annotations

import pytest

from cre_monitor.skills import editor
from cre_monitor.skills.editor import load_draft, save_skill
from cre_monitor.skills.registry import get_registry
from cre_monitor.versioned import ConflictError
from tests.support.samples import skill_draft



def test_save_keeps_history_clears_caches_and_detects_conflicts():
    draft, version = load_draft("office-rents")
    old_text = editor.skill_path("office-rents").read_text(encoding="utf-8")
    draft.description = "Prime and Grade A rents across London submarkets - edited in the UI."
    save_skill(draft, expected_version=version)
    assert get_registry().get("office-rents").meta.description.endswith("edited in the UI.")   # cache rebuilt
    (v,) = editor.versions("office-rents")
    assert v.read_text(encoding="utf-8") == old_text
    with pytest.raises(ConflictError):
        save_skill(draft, expected_version=version)                     # stale version: someone saved since
    editor.restore_version("office-rents", v)
    assert get_registry().get("office-rents").meta.description.startswith("Prime and Grade A office rents")


def test_create_new_skill_runs_in_a_demo_brief():
    from cre_monitor.graph.builder import run_brief

    save_skill(skill_draft(), is_new=True)
    assert "lease-events" in [s.name for s in get_registry().brief_skills()]
    (finding,) = run_brief(["lease-events"])["findings"]
    assert finding.error is None and "No demo data" in finding.headline


def test_delete_restore_and_protection():
    orphaned = editor.orphaned_metrics("office-rents")
    assert "grade_a_rent" in orphaned and "prime_rent" not in orphaned   # submarket-dynamics also has prime_rent
    editor.delete_skill("office-rents")
    assert "office-rents" not in get_registry()
    ((trash_id, name, _),) = editor.list_trash()
    assert name == "office-rents"
    assert editor.restore_skill(trash_id) == "office-rents" and "office-rents" in get_registry()
    with pytest.raises(ValueError, match="cannot be deleted"):
        editor.delete_skill("market-synthesis")
    # Restoring onto an existing name is refused.
    editor.delete_skill("news-events")
    save_skill(skill_draft(name="news-events"), is_new=True)
    with pytest.raises(ValueError, match="exists already"):
        editor.restore_skill(editor.list_trash()[0][0])


def test_attach_and_detach_metric():
    from cre_monitor.catalog import MetricDef, add_metric

    add_metric(MetricDef(key="average_lease_length", label="Average lease length", unit="years"))
    editor.attach_metric("leasing-take-up", "average_lease_length", sanity_range=(1, 25),
                         guidance="Brokers' quarterly reports state the average term of new leases.",
                         domains=["savills.co.uk"])
    skill = get_registry().get("leasing-take-up")
    assert "average_lease_length" in skill.meta.metrics and skill.meta.sanity_ranges["average_lease_length"] == (1, 25)
    assert "## Additional metrics" in skill.instructions and "### `average_lease_length`" in skill.instructions
    assert editor.detach_metric("average_lease_length") == ["leasing-take-up"]
    assert "average_lease_length" not in get_registry().get("leasing-take-up").meta.metrics
