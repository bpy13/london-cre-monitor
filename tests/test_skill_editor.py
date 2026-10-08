"""Skill editor backend: round trip, validation, save/history/conflicts, create, delete/restore,
metric attach/detach and path safety. Works on per-test copies of skills/ (conftest)."""

from __future__ import annotations

import pytest

from cre_monitor.skills import editor
from cre_monitor.skills.editor import SkillDraft, load_draft, save_skill, validate_draft
from cre_monitor.skills.registry import get_registry
from cre_monitor.versioned import ConflictError

INSTRUCTIONS = ("# Lease events\n\n## Goal\nTrack lease expiries and break options in central London.\n\n"
                "## Method\nSearch broker reports and news for lease events.")


def _new(**kw) -> SkillDraft:
    return SkillDraft(**({"name": "lease-events", "description": "Lease expiries and breaks across central London.",
                          "tools": ["web_search"], "metrics": [], "instructions": INSTRUCTIONS} | kw))


def test_every_repo_skill_round_trips_through_the_editor():
    for skill in get_registry().all():
        draft, _ = load_draft(skill.name)
        assert validate_draft(draft, is_new=False) == [], skill.name
        reparsed = SkillDraft.model_validate({**draft.model_dump()})
        assert reparsed.frontmatter_dict() == draft.frontmatter_dict()


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


def test_validation_explains_problems_in_plain_english():
    problems = validate_draft(_new(name="Lease Events!", tools=[], metrics=["nope"], instructions="short",
                                   sanity_ranges={"prime_rent": (1, 2)}), is_new=True)
    text = "\n".join(problems)
    assert "Name:" in text and "choose at least one tool" in text and "unknown metric keys ['nope'" in text
    assert "too short" in text and "not in this skill's metrics" in text
    assert "already exists" in "\n".join(validate_draft(_new(name="office-rents"), is_new=True))
    with pytest.raises(ValueError, match="Name:"):
        save_skill(_new(name="Bad Name"), is_new=True)


def test_create_new_skill_runs_in_a_demo_brief():
    from cre_monitor.graph.builder import run_brief

    save_skill(_new(), is_new=True)
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
    save_skill(_new(name="news-events"), is_new=True)
    with pytest.raises(ValueError, match="exists already"):
        editor.restore_skill(editor.list_trash()[0][0])


def test_path_tricks_are_refused():
    with pytest.raises(ValueError):
        editor.delete_skill("../catalog")
    with pytest.raises(ValueError):
        editor.restore_skill("../../skills/office-rents__x")
    with pytest.raises(ValueError):
        editor.load_draft("../catalog")


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


def test_git_changes_is_empty_outside_the_repo():
    assert editor.git_changes() == []                                    # tests use temp copies
