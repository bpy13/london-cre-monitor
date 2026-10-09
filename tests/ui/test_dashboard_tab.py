"""Dashboard tab: tracked metric cards, metric tracking, submarkets."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from cre_monitor.catalog import get_catalog
from tests.support.apptest import APP


def test_dashboard_overview_shows_tracked_cards_and_detail():
    from cre_monitor.schemas import Metric, SkillFinding
    from cre_monitor.store import get_store

    places = ["Central London", "City", "West End", "Canary Wharf", "Midtown", "Paddington"]
    get_store().seed_from_fixture()
    get_store().record("t1", [SkillFinding(skill="office-rents", headline="h", summary="s", metrics=[
        Metric(key="prime_rent", submarket=p, value=100.0 + i, unit="GBP psf pa", period="2026-Q2", source="JLL")
        for i, p in enumerate(places)])])
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, at.exception
    labels = [m.label for m in at.metric]
    assert {"Prime rent", "Vacancy rate", "Bank Rate", "10-year gilt yield"} <= set(labels)
    assert at.selectbox(key="dash-metric").value == "prime_rent"
    places = at.multiselect(key="dash-places-prime_rent")
    assert len(places.value) > 4                                       # no 4-submarket cap any more
    at.selectbox(key="dash-metric").set_value("bank_rate").run()
    assert not at.exception, at.exception


def test_untracking_a_metric_hides_its_card_and_saves_the_catalogue():
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.checkbox(key="track-prime_yield").uncheck().run()
    assert not at.exception, at.exception
    assert not get_catalog().metric("prime_yield").tracked
    assert "Prime yield" not in [m.label for m in at.metric]
    assert any("no longer tracked" in s.value for s in at.success)
    at.checkbox(key="track-rent_free_months").check().run()
    assert "Rent-free period" in [m.label for m in at.metric]


def test_add_and_remove_submarket_from_ui():
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.text_input(key="add-sm-name").input("Victoria")
    at.text_input(key="add-sm-aliases").input("SW1")
    next(b for b in at.button if b.label == "Add submarket").click().run()
    assert not at.exception, at.exception
    assert get_catalog().canonical_place("sw1") == "Victoria"
    at.button(key="rm-sm-Victoria").click().run()
    assert "Victoria" not in get_catalog().all_places()
    assert at.button(key="rm-sm-Paddington") and not [b for b in at.button if b.key == "rm-sm-Central London"]


def test_edit_metric_definition_and_html_is_escaped():
    """✏️ edits a metric's name/definition; user text never renders as HTML (stored-XSS guard)."""
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.text_area(key="edit-def-prime_yield").input('Net initial yield <img src=x onerror="alert(1)">')
    at.button(key="edit-save-prime_yield").click().run()
    assert not at.exception, at.exception
    assert get_catalog().metric("prime_yield").definition.startswith("Net initial yield")
    rendered = " ".join(m.value for m in at.markdown)
    assert "&lt;img" in rendered and "<img" not in rendered


def test_run_mode_toggles_only_in_debug_mode():
    """Offline/demo switches are server-wide, so ordinary users only see the current mode."""
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not [t for t in at.toggle if t.label.startswith(("Offline data", "Demo mode"))]
    assert any("set by the administrator" in c.value for c in at.caption)
