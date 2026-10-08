"""Claude-assisted authoring (metric feasibility, skill drafts, reviews) with the fake LLM."""

from __future__ import annotations

import pytest

from cre_monitor import authoring
from cre_monitor.authoring import MetricAssessment, NeedsLiveMode, RangeItem, SkillReview, _DraftOut
from cre_monitor.catalog import get_catalog
from cre_monitor.schemas import Metric
from cre_monitor.skills.registry import get_registry
from tests.support.fake_llm import submit_call


LEASE = MetricAssessment(
    verdict="needs_skill_change", reasoning="Brokers publish average lease terms quarterly.",
    key="average_lease_length", label="Average lease length", unit="years", group="Leasing",
    definition="Mean term of office leases signed in the period.", target_skill="leasing-take-up",
    sanity_min=1, sanity_max=25, guidance="Look for 'average lease length' in quarterly reports.",
    preferred_domains=["savills.co.uk"], likely_sources=["Savills (quarterly)"],
)


def test_exact_match_needs_no_llm_even_in_demo_mode():
    a = authoring.assess_metric("Prime rent")
    assert a.verdict == "already_collected" and a.existing_key == "prime_rent"
    assert authoring.assess_metric("rent_free_months").existing_key == "rent_free_months"
    with pytest.raises(NeedsLiveMode):
        authoring.assess_metric("average lease length for new City lettings")


def test_needs_skill_change_is_applied_to_catalogue_and_skill(fake_llm):
    fake_llm.structured["MetricAssessment"] = LEASE
    a = authoring.assess_metric("average lease length for new City lettings")
    assert a.verdict == "needs_skill_change" and a.target_skill == "leasing-take-up"
    system = fake_llm.calls[-1][0].content
    assert "AVAILABLE TOOLS" in system and "leasing-take-up" in system and "prime_rent" in system
    message = authoring.apply_assessment(a)
    assert "Added 'Average lease length'" in message
    m = get_catalog().metric("average_lease_length")
    assert m.tracked and m.unit == "years"
    skill = get_registry().get("leasing-take-up")
    assert "average_lease_length" in skill.meta.metrics and "savills.co.uk" in skill.meta.preferred_domains


def test_model_answers_are_revalidated(fake_llm):
    fake_llm.structured["MetricAssessment"] = LEASE.model_copy(update={"target_skill": "no-such-skill"})
    assert authoring.assess_metric("lease length").verdict == "not_feasible"           # bad skill -> downgraded
    fake_llm.structured["MetricAssessment"] = LEASE.model_copy(update={"key": "prime_rent", "label": "Prime rent"})
    a = authoring.assess_metric("top rents")
    assert a.verdict == "already_collected" and a.existing_key == "prime_rent"         # existing key -> just track
    fake_llm.structured["MetricAssessment"] = MetricAssessment(verdict="already_collected", existing_key="ghost",
                                                               reasoning="r")
    assert authoring.assess_metric("ghost metric").verdict == "not_feasible"


def test_not_feasible_changes_nothing(fake_llm):
    fake_llm.structured["MetricAssessment"] = MetricAssessment(
        verdict="not_feasible", reasoning="Only in CoStar.", developer_changes="A licensed CoStar feed as a tool.")
    a = authoring.assess_metric("asking rent by building")
    before = get_catalog().version
    with pytest.raises(ValueError, match="nothing was changed"):
        authoring.apply_assessment(a)
    assert get_catalog().version == before


def test_failed_skill_change_rolls_back_the_catalogue_entry(fake_llm, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(authoring, "attach_metric", boom)
    with pytest.raises(RuntimeError):
        authoring.apply_assessment(LEASE)
    assert get_catalog().metric("average_lease_length") is None


def test_test_run_reports_whether_the_metric_came_back(fake_llm):
    authoring.apply_assessment(LEASE)
    finding = fake_llm.macro.model_copy(update={"metrics": [Metric(
        key="average_lease_length", submarket="Central London", value=7.2, unit="years", period="2026-Q2",
        source="Savills", url="https://www.savills.co.uk/")]})
    fake_llm.responses[:] = [submit_call(finding)]
    found, result = authoring.test_metric(LEASE)
    assert found and result.metrics[0].value == 7.2
    assert "average lease length" in str(fake_llm.calls[-1][1].content).lower()


def test_draft_skill_drops_unknown_tools_and_metrics(fake_llm):
    fake_llm.structured["_DraftOut"] = _DraftOut(
        description="Lease expiries and break options across central London offices.",
        tools=["web_search", "costar_api"], metrics=["vacancy_rate", "lease_expiry_sqft"],
        sanity_ranges=[RangeItem(metric="vacancy_rate", min=30, max=0), RangeItem(metric="lease_expiry_sqft", min=0, max=1)],
        keywords=["Expiry"], instructions="# Lease events\n\n## Goal\n" + "Track lease events. " * 10,
        missing_metrics=["lease_expiry_sqft (sq ft): space with leases expiring in the year"],
    )
    draft, notes = authoring.draft_skill("lease-events", "lease expiries and breaks")
    assert draft.tools == ["web_search"] and draft.metrics == ["vacancy_rate"]
    assert draft.sanity_ranges == {"vacancy_rate": (0, 30)} and draft.keywords == ["expiry"]
    assert any("costar_api" in n for n in notes) and any("Suggested new metrics" in n for n in notes)
    assert "EXAMPLE SKILL.md" in fake_llm.calls[-1][0].content


def test_review_skill(fake_llm):
    from cre_monitor.skills.editor import load_draft

    fake_llm.structured["SkillReview"] = SkillReview(ok=False, summary="Method is vague.",
                                                     issues=["No example queries."])
    review = authoring.review_skill(load_draft("office-rents")[0])
    assert not review.ok and review.issues == ["No example queries."]
    assert "name: office-rents" in fake_llm.calls[-1][1].content
