"""Performance-check scoring: number matching, figure accuracy, grounding, readability."""

from __future__ import annotations

import pytest

from cre_monitor.benchmark import scoring
from cre_monitor.catalog import get_catalog
from tests.support.samples import agent_metric, key_entry


def test_numbers_are_found_whatever_the_format():
    assert scoring.numbers_in_text("2.6m sq ft, £1.2bn, 6.3%, 1,250,000 and 450k") == [2.6e6, 1.2e9, 6.3, 1.25e6, 4.5e5]
    assert scoring.value_in_text(2_600_000, "take-up of 2.6 million sq ft")
    assert scoring.value_in_text(6.3, "vacancy of 6.3%") and not scoring.value_in_text(6.4, "vacancy of 6.3%")
    assert not scoring.value_in_text(2, "Q2 2026")                      # period labels are not figures


def test_figure_scoring_coverage_accuracy_sources_and_grounding():
    entries = [key_entry(id="a"), key_entry(id="b", key="vacancy_rate", value=6.3, unit="%"),
               key_entry(id="c", key="prime_rent", submarket="West End", value=190, unit="GBP psf pa")]
    metrics = [
        agent_metric(),                                                                    # exact, same source
        agent_metric(key="vacancy_rate", value=6.5, unit="%", source="Savills", url=""),   # other source, off by 0.2pp
        agent_metric(key="prime_rent", submarket="City", value=95, unit="GBP psf pa"),     # different place: no match
    ]
    tool_texts = ["Central London take-up totalled 2.6m sq ft in Q2 2026. Vacancy 6.3%."]
    s = scoring.score_figures(entries, metrics, tool_texts, units=get_catalog().units())
    assert (s.n_entries, s.found, s.accurate) == (3, 2, 1)
    assert s.coverage == 66.7 and s.accuracy == 50.0
    assert s.accuracy_same_source == 100.0 and s.accuracy_other_source == 0.0
    by_id = {r.entry_id: r for r in s.results}
    assert by_id["a"].status == "accurate" and by_id["a"].grounded
    assert by_id["b"].status == "inaccurate" and not by_id["b"].same_source and not by_id["b"].grounded
    assert by_id["c"].status == "missing"
    assert s.grounding == pytest.approx(33.3)                             # 1 of 3 agent figures seen in tools
    # Tolerances: rates in percentage points, others relative.
    assert scoring.is_accurate(6.3, 6.39, "%", 0.1, 0.02) and not scoring.is_accurate(6.3, 6.45, "%", 0.1, 0.02)
    assert scoring.is_accurate(100, 101.9, "GBP psf pa", 0.1, 0.02)


def test_readability_statistics():
    plain = "Rents rose in Q2 2026. Vacancy fell to 6.3% in Q2 2026. Demand is strong."
    dense = ("Notwithstanding considerable macroeconomic uncertainty and persistently elevated financing costs, "
             "institutional occupational demand demonstrated remarkable resilience, characterised by "
             "unprecedented concentration within exceptionally high-specification accommodation offering "
             "comprehensive sustainability credentials and amenity provision across multiple submarkets.")
    p, d = scoring.readability(plain), scoring.readability(dense)
    assert p.flesch > d.flesch and p.avg_sentence_words < d.avg_sentence_words
    assert d.pct_long_sentences == 100.0 and p.pct_long_sentences == 0.0
    assert p.pct_figures_with_period == 100.0
    assert scoring.readability("").flesch is None
