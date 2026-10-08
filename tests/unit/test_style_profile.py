"""House style: heuristic learning, example files, library roles, layout, number guard."""

from __future__ import annotations

import pytest

from cre_monitor.config import get_settings
from cre_monitor.style import file_roles, save_example, set_roles
from cre_monitor.style.editor import StyledTopic, guard_ok, numbers_in
from cre_monitor.style.profile import (
    DEFAULT_LAYOUT, LayoutSection, StyleProfile, delete_example, learn_profile, list_examples, load_profile,
    read_example, resolve_layout,
)
from tests.support.samples import REPORT, style_finding


def test_library_roles_default_and_update():
    save_example("ref.md", REPORT.encode())
    assert file_roles("ref.md") == {"style": True, "benchmark": False}
    set_roles("ref.md", benchmark=True, style=False)
    from cre_monitor.style import examples_with_role
    assert [p.name for p in examples_with_role("benchmark")] == ["ref.md"]
    assert examples_with_role("style") == []
    with pytest.raises(ValueError, match="No report"):
        set_roles("ghost.md", benchmark=True)


def test_heuristic_learning_captures_layout_conventions_and_techniques(examples):
    profile = learn_profile()                                   # demo mode -> heuristic
    assert profile.method == "heuristic" and profile.sources == ["a.md", "b.md"]   # README skipped
    layout = [(s.section, s.title) for s in profile.layout]
    assert ("summary", "Key themes") in layout and ("watch_list", "Outlook") in layout
    assert [s for s, _ in layout].index("summary") < [s for s, _ in layout].index("watch_list")
    assert "psf" in profile.number_style and "basis points" in profile.number_style
    assert any("long-term average" in t.lower() for t in profile.techniques)
    assert "we" in profile.voice                                # first person plural detected
    # Saved for reuse and review.
    assert load_profile() == profile
    assert (get_settings().style_dir / "profile.md").read_text(encoding="utf-8").startswith("# House style")


def test_no_examples_is_a_clear_error():
    with pytest.raises(ValueError, match="No example reports"):
        learn_profile()


def test_html_examples_are_read(tmp_path):
    page = tmp_path / "r.html"
    page.write_text("<html><body><article><h2>Key themes</h2><p>Prime rents rose to £190 psf in the "
                    "West End during the second quarter, supported by strong demand.</p></article></body></html>",
                    encoding="utf-8")
    assert "£190 psf" in read_example(page)


def test_save_and_delete_examples_stay_inside_the_examples_folder():
    folder = get_settings().style_dir / "reports"
    assert save_example("../../escape.md", b"# hi") == folder / "escape.md"       # base name only
    assert save_example("..\\..\\win.txt", b"hi") == folder / "win.txt"
    for bad in ("evil.exe", "README.md", ".hidden.md", "noext", ""):
        with pytest.raises(ValueError):
            save_example(bad, b"x")
    assert [p.name for p in list_examples()] == ["escape.md", "win.txt"]
    assert delete_example("escape.md") and not delete_example("escape.md")
    with pytest.raises(ValueError):
        delete_example("../profile.json")                                          # can't reach the profile


def test_resolve_layout_orders_retitles_and_never_drops_sections():
    assert resolve_layout(None) == DEFAULT_LAYOUT
    profile = StyleProfile(name="x", voice="v", layout=[
        LayoutSection(section="summary", title="Key themes"),
        LayoutSection(section="watch_list", title="Outlook"),
        LayoutSection(section="summary", title="duplicate ignored"),
    ])
    layout = resolve_layout(profile)
    assert layout[:2] == [("summary", "Key themes"), ("watch_list", "Outlook")]
    assert {s for s, _ in layout} == {s for s, _ in DEFAULT_LAYOUT}  # all sections still rendered
    assert dict(layout)["sources"] == "Sources"                       # default heading for omitted ones
    assert [s for s, _ in layout][-2:] == ["data_quality", "sources"]


def test_missing_sections_go_before_references_the_profile_placed():
    profile = StyleProfile(name="x", voice="v", layout=[
        LayoutSection(section="summary", title="At a glance"),
        LayoutSection(section="sources", title="References"),
    ])
    order = [s for s, _ in resolve_layout(profile)]
    assert order[0] == "summary" and order[-2:] == ["sources", "data_quality"]
    assert order.index("what_changed") < order.index("sources")       # not appended after References
    assert order.index("topics") < order.index("sources")


def test_number_guard():
    f = style_finding()
    assert numbers_in("2,600,000 and 3.750") == {"2600000", "3.75"}
    assert guard_ok(f, StyledTopic(skill=f.skill, headline="West End prime: £190 psf (Q2 2026)",
                                   summary="Up 8% y/y.", insights=["City: £95 psf."]))
    assert not guard_ok(f, StyledTopic(skill=f.skill, headline="Prime rents hit £195 psf",   # changed figure
                                       summary="Up 8%.", insights=[]))
