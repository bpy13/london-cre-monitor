"""Skill registry: every SKILL.md in the repo must load, and bad ones must be rejected."""

from __future__ import annotations

from pathlib import Path

from cre_monitor.skills.registry import SkillRegistry, get_registry
from cre_monitor.tools import TOOL_NAMES

EXPECTED_RESEARCH_SKILLS = {
    "office-rents", "vacancy-availability", "leasing-take-up", "supply-pipeline",
    "submarket-dynamics", "macro-economy", "occupier-demand", "news-events",
}


def test_all_repo_skills_are_valid():
    reg = get_registry()
    assert reg.errors == {}, f"Invalid SKILL.md files: {reg.errors}"
    assert {s.name for s in reg.research_skills()} == EXPECTED_RESEARCH_SKILLS
    assert "market-synthesis" in reg and not reg.get("market-synthesis").meta.tools


def test_brief_skills_are_ordered_and_have_instructions():
    skills = get_registry().brief_skills()
    orders = [s.meta.order for s in skills]
    assert orders == sorted(orders)
    for s in skills:
        assert len(s.instructions) > 200, f"{s.name} instructions look empty"
        assert set(s.meta.tools) <= set(TOOL_NAMES)
        assert s.meta.keywords, f"{s.name} needs keywords for fallback routing"


def test_planner_catalog_only_shows_descriptions():
    catalog = get_registry().planner_catalog()
    assert "office-rents:" in catalog
    assert "## Method" not in catalog  # progressive disclosure: no bodies


def _write_skill(root: Path, folder: str, frontmatter: str, body: str = "Body " * 50) -> None:
    (root / folder).mkdir(parents=True)
    (root / folder / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")


def test_invalid_skills_are_reported_not_raised(tmp_path):
    _write_skill(tmp_path, "good", "name: good\ndescription: A perfectly fine skill description.\ntools: [web_search]")
    _write_skill(tmp_path, "wrong-name", "name: other\ndescription: Name does not match the folder name.")
    _write_skill(tmp_path, "bad-metric", "name: bad-metric\ndescription: Declares a metric key that does not exist.\nmetrics: [made_up]")
    _write_skill(tmp_path, "bad-tool", "name: bad-tool\ndescription: References a tool that is not registered.\ntools: [teleport]")

    reg = SkillRegistry(tmp_path, available_tools=set(TOOL_NAMES))
    assert reg.names() == ["good"]
    assert set(reg.errors) == {"wrong-name", "bad-metric", "bad-tool"}
