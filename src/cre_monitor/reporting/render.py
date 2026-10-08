"""Render the market brief to HTML (interactive) and Markdown (with PNG charts).

Output layout::

    reports/2026-10-07/
        brief_<run_id>.html              # self-contained page, Plotly loaded from CDN
        brief_<run_id>.md                # same content for email / wiki / git diffs
        charts/<run_id>/<chart_id>.png   # static charts referenced by the Markdown
        findings_<run_id>.json           # raw structured output (audit trail)

Charts get a folder per run so that several briefs on the same day don't
overwrite each other's PNGs (each Markdown file keeps pointing at its own charts).

The HTML template lives in ``reporting/templates/report.html.j2``.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from cre_monitor.config import get_settings
from cre_monitor.errors import Incident, classify
from cre_monitor.reporting.charts import build_charts
from cre_monitor.schemas import Citation, ExecutiveSynthesis, MetricDelta, SkillFinding, ValidationIssue
from cre_monitor.skills import get_registry
from cre_monitor.store import get_store

logger = logging.getLogger(__name__)

#: Headline KPI tiles: (label, metric key, submarket, format).
KPI_TILES = [
    ("Prime rent - West End", "prime_rent", "West End", "£{:,.2f} psf"),
    ("Prime rent - City", "prime_rent", "City", "£{:,.2f} psf"),
    ("Vacancy - Central London", "vacancy_rate", "Central London", "{:.1f}%"),
    ("Take-up - latest quarter", "take_up_sqft", "Central London", "{:,.0f} sq ft"),
    ("Bank Rate", "bank_rate", "UK", "{:.2f}%"),
]


def _env() -> Environment:
    env = Environment(
        loader=PackageLoader("cre_monitor.reporting", "templates"),
        # Escape HTML templates only; the Markdown template must stay raw.
        autoescape=select_autoescape(enabled_extensions=("html.j2",), default=False),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["label"] = lambda key: key.replace("_", " ")
    # Raw exception text -> plain-English title, e.g. "The AI service refused the request".
    env.filters["error_title"] = lambda text: classify(text or "").title
    return env


def build_kpis(findings: list[SkillFinding], deltas: list[MetricDelta]) -> list[dict]:
    """Values for the KPI tiles, each with its change vs the previous period."""
    delta_map = {(d.key, d.submarket): d for d in deltas}
    tiles = []
    for label, key, submarket, fmt in KPI_TILES:
        metric = next(
            (m for f in findings if not f.error for m in sorted(f.metrics, key=lambda x: x.period, reverse=True)
             if m.key == key and m.submarket == submarket),
            None,
        )
        if metric is None:
            continue
        d = delta_map.get((key, submarket))
        change = None
        if d:
            if d.unit == "%":
                change = f"{d.change:+.2f}pp vs {d.previous_period}"
            elif d.pct_change is not None:
                change = f"{d.pct_change:+.1f}% vs {d.previous_period}"
            if change and not d.same_source:
                # Different brokers' definitions differ - flag rather than hide.
                change += f" ({d.previous_source}, not like-for-like)"
        tiles.append({
            "label": label, "value": fmt.format(metric.value), "period": metric.period,
            "source": metric.source, "change": change,
            "direction": None if not d else ("up" if d.change > 0 else "down" if d.change < 0 else "flat"),
        })
    return tiles


def all_citations(findings: list[SkillFinding]) -> list[Citation]:
    """De-duplicated citations across findings, keyed by URL."""
    seen: dict[str, Citation] = {}
    for f in findings:
        for c in f.citations:
            seen.setdefault(c.url or c.title, c)
    return sorted(seen.values(), key=lambda c: (c.publisher, c.title))


def _ordered(findings: list[SkillFinding]) -> list[SkillFinding]:
    """Sort findings in the report order declared by each skill's ``order``."""
    order = {name: i for i, name in enumerate(get_registry().names())}
    return sorted(findings, key=lambda f: order.get(f.skill, 999))


def export_pngs(figures: dict, charts_dir: Path, rel_prefix: str) -> dict[str, str]:
    """Write static PNG copies of the charts (for the Markdown report).

    Args:
        figures: ``chart_id -> Figure``.
        charts_dir: Folder to write the PNGs into (must exist).
        rel_prefix: Path of ``charts_dir`` relative to the Markdown file, used in
            the returned links, e.g. ``"charts/<run_id>"``.

    Uses ``plotly.io.write_images`` so all charts are rendered in ONE headless
    Chrome session (kaleido v1 starts a browser per call otherwise, which is
    slow: ~4s per chart). Failure is non-fatal: kaleido needs a local
    Chrome/Chromium (run ``plotly_get_chrome`` to install one), and the HTML
    report still has interactive charts.

    Returns:
        ``chart_id -> relative path`` for the charts that were written.
    """
    import plotly.graph_objects as go
    import plotly.io as pio

    ids = list(figures)
    try:
        pio.write_images(
            # Copies: the export can stamp a fixed width onto the figure, which
            # would then make the responsive HTML version overflow its card.
            [go.Figure(figures[i]) for i in ids],
            [charts_dir / f"{i}.png" for i in ids],
            width=900,
            height=[figures[i].layout.height or 380 for i in ids],
            scale=2,
        )
        return {i: f"{rel_prefix}/{i}.png" for i in ids}
    except Exception as exc:  # noqa: BLE001
        logger.warning("PNG export failed (%s); Markdown report will omit charts", exc)
        return {}


def write_report(
    run_id: str,
    synthesis: ExecutiveSynthesis,
    findings: list[SkillFinding],
    deltas: list[MetricDelta],
    issues: list[ValidationIssue],
    out_dir: Path | None = None,
    incident: Incident | None = None,
) -> dict[str, Path]:
    """Render and save the report files.

    Args:
        run_id: Run identifier (part of file names).
        synthesis: Executive synthesis from the synthesis node.
        findings: Validated findings.
        deltas: Period-on-period changes.
        issues: Validation issues to disclose in the report.
        out_dir: Override output folder (defaults to ``reports/<today>``).
        incident: Failures of this run, shown as a user-friendly problem panel
            with a reference ID. Raw error text appears only in the collapsed
            "Technical details" section (HTML) / appendix (Markdown).

    Returns:
        Mapping of output kind (``html``, ``markdown``, ``json``) to path.
    """
    s = get_settings()
    out_dir = out_dir or s.reports_dir / date.today().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)

    findings = _ordered(findings)
    figures = build_charts(findings, get_store())

    png_paths: dict[str, str] = {}
    if s.report_png:
        # One folder per run: same-day briefs must not overwrite each other's PNGs.
        rel_prefix = f"charts/{run_id}"
        charts_dir = out_dir / rel_prefix
        charts_dir.mkdir(parents=True, exist_ok=True)
        png_paths = export_pngs(figures, charts_dir, rel_prefix)

    chart_html = {
        # default_width=100% makes each chart fill its card; without it Plotly first
        # draws at 700px and overflows narrower cards (clipping the bars).
        cid: fig.to_html(full_html=False, include_plotlyjs=False, default_width="100%",
                         config={"displaylogo": False, "responsive": True})
        for cid, fig in figures.items()
    }
    skills_meta = {s.name: s.meta for s in get_registry().all()}
    ctx = {
        "run_id": run_id,
        "generated": datetime.now().strftime("%d %B %Y, %H:%M"),
        "demo_mode": s.cre_demo_mode,
        "offline": s.cre_offline,
        "synthesis": synthesis,
        "kpis": build_kpis(findings, deltas),
        "findings": findings,
        "skills_meta": skills_meta,
        "deltas": [d.describe() for d in deltas if d.is_material],
        # Skill failures are explained by the incident panel; don't repeat raw errors as data notes.
        "issues": [i for i in issues if not (incident and i.message.startswith("Skill failed:"))],
        "incident": incident,
        "support_contact": s.support_contact,
        "charts": chart_html,
        "png_charts": png_paths,
        "citations": all_citations(findings),
    }
    env = _env()
    stem = f"brief_{run_id}"
    paths = {
        "html": out_dir / f"{stem}.html",
        "markdown": out_dir / f"{stem}.md",
        "json": out_dir / f"findings_{run_id}.json",
    }
    paths["html"].write_text(env.get_template("report.html.j2").render(**ctx), encoding="utf-8")
    paths["markdown"].write_text(env.get_template("report.md.j2").render(**ctx), encoding="utf-8")
    paths["json"].write_text(
        json.dumps(
            {
                "run_id": run_id,
                "synthesis": synthesis.model_dump(mode="json"),
                "findings": [f.model_dump(mode="json") for f in findings],
                "deltas": [d.model_dump(mode="json") for d in deltas],
                "issues": [i.model_dump(mode="json") for i in issues],   # unfiltered: full audit trail
                "incident": incident.model_dump(mode="json") if incident else None,
            },
            indent=2, ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return paths
