"""Metric and submarket catalogue: loading, edits, protection, history and conflicts.

conftest.py points CATALOG_DIR / SKILLS_DIR at per-test copies, so these edits
never touch the repo's files.
"""

from __future__ import annotations

import pytest

from cre_monitor import catalog
from cre_monitor.catalog import (
    PROTECTED_METRICS, PROTECTED_SUBMARKETS, MetricDef, SubmarketDef, add_metric, add_submarket, get_catalog,
    remove_metric, remove_submarket, set_tracked, suggest_key, update_metric, update_submarket,
)
from cre_monitor.skills.registry import get_registry
from cre_monitor.versioned import ConflictError, list_versions


def _lease_length(**kw) -> MetricDef:
    return MetricDef(**({"key": "average_lease_length", "label": "Average lease length", "unit": "years",
                         "group": "Leasing", "definition": "Mean term of new leases."} | kw))


def test_repo_catalogue_is_consistent_with_skills_and_code():
    cat = get_catalog()
    assert cat.units()["prime_rent"] == "GBP psf pa" and cat.units()["vacancy_rate"] == "%"
    assert [m.key for m in cat.tracked()] == ["prime_rent", "vacancy_rate", "take_up_sqft",
                                             "under_construction_sqft", "prime_yield", "bank_rate", "gilt_10y_yield"]
    assert PROTECTED_METRICS <= set(cat.units())                        # code-referenced keys all exist
    assert PROTECTED_SUBMARKETS <= set(cat.all_places())
    assert not get_registry().errors                                    # every skill's metrics are in the catalogue
    assert cat.macro_geographies() == ["UK", "London"] and "Canary Wharf" in cat.submarket_names()
    assert cat.canonical_place("docklands") == "Canary Wharf" and cat.canonical_place("Atlantis") is None


def test_add_metric_saves_file_keeps_history_and_unlocks_it_for_skills():
    before = catalog.metrics_path().read_text(encoding="utf-8")
    added = add_metric(_lease_length(tracked=True))
    assert added.added_at                                                # stamped
    text = catalog.metrics_path().read_text(encoding="utf-8")
    assert text.startswith("# Metric catalogue") and "average_lease_length" in text
    assert get_catalog().metric("average_lease_length").tracked
    # The previous file is in the history.
    (version,) = list_versions(catalog.history_dir(), "metrics.yaml")
    assert version.read_text(encoding="utf-8") == before
    # The skill registry was rebuilt against the new vocabulary.
    from cre_monitor.skills.registry import SkillMetadata
    SkillMetadata(name="x", description="a description long enough", metrics=["average_lease_length"])


def test_add_metric_rejects_bad_or_duplicate_entries():
    with pytest.raises(ValueError, match="snake_case"):
        _lease_length(key="Average Lease")
    with pytest.raises(ValueError, match="already exists"):
        add_metric(_lease_length(key="prime_rent"))
    with pytest.raises(ValueError, match="already exists"):
        add_metric(_lease_length(label="prime RENT"))                    # label clash, case-insensitive
    assert suggest_key("Average lease length (years)") == "average_lease_length_years"
    assert suggest_key("10y average") == "m_10y_average"


def test_concurrent_edit_is_refused():
    version = get_catalog().version
    set_tracked("rent_free_months", True)                                 # someone else saves first
    with pytest.raises(ConflictError, match="changed since you opened it"):
        set_tracked("grade_a_rent", True, expected_version=version)
    set_tracked("grade_a_rent", True, expected_version=get_catalog().version)   # fresh version works


def test_tracking_and_updating_metrics():
    set_tracked("prime_yield", False)
    assert "prime_yield" not in [m.key for m in get_catalog().tracked()]
    update_metric("prime_yield", definition="Net initial yield on prime offices.")
    assert get_catalog().metric("prime_yield").definition == "Net initial yield on prime offices."
    with pytest.raises(ValueError, match="Cannot change"):
        update_metric("prime_yield", key="other")


def test_remove_metric_is_protected_and_requires_detaching_from_skills():
    with pytest.raises(ValueError, match="cannot be removed"):
        remove_metric("prime_rent")
    with pytest.raises(ValueError, match="still collected by skill"):
        remove_metric("rent_free_months")                                 # office-rents lists it
    add_metric(_lease_length())
    remove_metric("average_lease_length")
    assert get_catalog().metric("average_lease_length") is None


def test_submarkets_add_update_remove():
    add_submarket(SubmarketDef(name="Victoria", aliases=["Victoria & Westminster"], description="SW1"))
    assert get_catalog().canonical_place("victoria & westminster") == "Victoria"
    # A new name that is an alias elsewhere would file figures in two places.
    with pytest.raises(ValueError, match="alias of 'Canary Wharf'"):
        add_submarket(SubmarketDef(name="Docklands"))
    with pytest.raises(ValueError, match="already name"):
        add_submarket(SubmarketDef(name="city"))
    with pytest.raises(ValueError, match="already belongs to 'Canary Wharf'"):
        update_submarket("Victoria", aliases=["E14"])
    update_submarket("Victoria", aliases=["SW1"])
    assert get_catalog().canonical_place("sw1") == "Victoria"
    with pytest.raises(ValueError, match="cannot be removed"):
        remove_submarket("Central London")
    remove_submarket("Victoria")
    assert "Victoria" not in get_catalog().all_places()


def test_new_submarket_and_metric_reach_the_research_prompt():
    from cre_monitor.graph.nodes.skill_runner import build_system_prompt

    add_submarket(SubmarketDef(name="Victoria"))
    add_metric(_lease_length())
    prompt = build_system_prompt(get_registry().get("office-rents"))
    assert "Victoria" in prompt and "average_lease_length (years)" in prompt
