"""Skill editor: round trip, validation messages, path safety."""

from __future__ import annotations

import pytest

from cre_monitor.skills import editor
from cre_monitor.skills.editor import SkillDraft, load_draft, save_skill, validate_draft
from cre_monitor.skills.registry import get_registry
from tests.support.samples import skill_draft



def test_every_repo_skill_round_trips_through_the_editor():
    for skill in get_registry().all():
        draft, _ = load_draft(skill.name)
        assert validate_draft(draft, is_new=False) == [], skill.name
        reparsed = SkillDraft.model_validate({**draft.model_dump()})
        assert reparsed.frontmatter_dict() == draft.frontmatter_dict()


def test_validation_explains_problems_in_plain_english():
    problems = validate_draft(skill_draft(name="Lease Events!", tools=[], metrics=["nope"], instructions="short",
                                   sanity_ranges={"prime_rent": (1, 2)}), is_new=True)
    text = "\n".join(problems)
    assert "Name:" in text and "choose at least one tool" in text and "unknown metric keys ['nope'" in text
    assert "too short" in text and "not in this skill's metrics" in text
    assert "already exists" in "\n".join(validate_draft(skill_draft(name="office-rents"), is_new=True))
    with pytest.raises(ValueError, match="Name:"):
        save_skill(skill_draft(name="Bad Name"), is_new=True)


def test_path_tricks_are_refused():
    with pytest.raises(ValueError):
        editor.delete_skill("../catalog")
    with pytest.raises(ValueError):
        editor.restore_skill("../../skills/office-rents__x")
    with pytest.raises(ValueError):
        editor.load_draft("../catalog")


def test_git_changes_is_empty_outside_the_repo():
    assert editor.git_changes() == []                                    # tests use temp copies
