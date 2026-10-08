"""📚 Reference reports tab: the report library, the house style, and the performance check.

Reports users supply (``style/reports/``, git-ignored) serve two purposes, chosen
per file in the **library**:

* **Style example** - the 🎨 House style learns voice, layout and techniques from
  them (moved here from the sidebar; see :mod:`cre_monitor.style`).
* **Benchmark** - the 🎯 Performance check measures the agent against them
  (see :mod:`cre_monitor.benchmark` and docs/EVALUATION.md):

  1. *Answer key*: Claude lists the figures and themes the report states; the
     analyst moderates them using the signals (in document, confidence,
     catalogue match, period) and accepts the right ones.
  2. *Figure run*: only the skills that collect those figures run, for that
     period; scored on coverage, accuracy, grounding and citations, with the
     estimated cost.
  3. *Brief judgement*: an existing brief rated against the reference
     (readability and citations free; rubric by Claude).
  4. *History*: earlier runs, to compare before/after a skill or prompt change.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from cre_monitor.config import get_settings
from cre_monitor.ui.components import render_incident


def _notice(kind: str, text: str) -> None:
    st.session_state.ref_notice = (kind, text)


def _show_notice() -> None:
    if notice := st.session_state.pop("ref_notice", None):
        kind, text = notice
        {"warning": st.warning, "error": st.error}.get(kind, st.success)(text)


def _incident(exc: Exception, step: str) -> None:
    from cre_monitor.errors import incident_from_exception

    render_incident(incident_from_exception(exc, step=step))


# --------------------------------------------------------------------------
# Library
# --------------------------------------------------------------------------

def _set_role(name: str, role: str) -> None:
    """Checkbox callback: save a file's role."""
    from cre_monitor.style import set_roles

    set_roles(name, **{role: st.session_state[f"role-{role}-{name}"]})


def library() -> None:
    from cre_monitor.style import SUPPORTED_SUFFIXES, delete_example, file_roles, list_examples, save_example

    st.caption("Reports you supply - an in-house monthly, broker quarterlies - stay on this machine (git-ignored). "
               "Tick what each is for: **Style** = the brief imitates its writing; **Benchmark** = the agent is "
               "measured against its figures. ⚖️ Check each report's licence first: some publishers prohibit use "
               "with AI tools.")
    # Changing the key after a save empties the uploader (Streamlit has no reset API).
    upload_key = f"style-upload-{st.session_state.get('style_upload_n', 0)}"
    uploads = st.file_uploader("Add reports", type=sorted(x.lstrip(".") for x in SUPPORTED_SUFFIXES),
                               accept_multiple_files=True, key=upload_key)
    if uploads and st.button(f"Save {len(uploads)} file(s)", key="style-save"):
        for f in uploads:
            try:
                save_example(f.name, f.getvalue())
            except ValueError as exc:
                st.error(str(exc))
        st.session_state.style_upload_n = st.session_state.get("style_upload_n", 0) + 1
        st.rerun()

    examples = list_examples()
    if not examples:
        st.info("No reports yet. Add some above.")
        return
    head = st.columns([0.62, 0.12, 0.14, 0.12])
    head[0].caption("Report")
    head[1].caption("Style")
    head[2].caption("Benchmark")
    for path in examples:
        roles = file_roles(path.name)
        c_name, c_style, c_bench, c_del = st.columns([0.62, 0.12, 0.14, 0.12], vertical_alignment="center")
        # Backticks: file names often contain "_" which Markdown would turn into italics.
        c_name.markdown(f"`{path.name}` <small>· {path.stat().st_size // 1024 + 1} KB</small>", unsafe_allow_html=True)
        for col, role in ((c_style, "style"), (c_bench, "benchmark")):
            st.session_state[f"role-{role}-{path.name}"] = roles[role]   # the file on disk is the truth
            col.checkbox(role, key=f"role-{role}-{path.name}", label_visibility="collapsed",
                         on_change=_set_role, args=(path.name, role))
        if c_del.button("🗑", key=f"style-del-{path.name}", help=f"Remove {path.name}"):
            delete_example(path.name)
            st.rerun()


# --------------------------------------------------------------------------
# House style (moved from the sidebar)
# --------------------------------------------------------------------------

def house_style() -> None:
    from cre_monitor.style import MAX_FILES, clear_profile, examples_with_role, learn_profile, load_profile

    s = get_settings()
    st.caption("Briefs can imitate the voice, layout, number conventions and techniques of the reports ticked as "
               "**Style**. Figures always come from the agent's research. Switch it off per brief in the sidebar "
               "(*Use house style*).")
    profile = load_profile()
    if profile is None:
        st.info("No house style yet - briefs use the built-in style.", icon="ℹ️")
    else:
        st.success(f"**{profile.name}**  \nLearned {profile.learned_at or '?'} via {profile.method} "
                   f"from {len(profile.sources)} report(s).", icon="🎨")
        if not s.report_style:
            st.warning("Not applied: REPORT_STYLE=0 is set.", icon="⚠️")
        if st.toggle("Show learned profile", key="style-show"):
            st.markdown(profile.to_markdown())
        if st.button("Clear house style", key="style-clear"):
            clear_profile()
            _notice("success", "House style removed - briefs use the built-in style.")
            st.rerun()

    style_files = examples_with_role("style")
    st.caption(f"{len(style_files)} report(s) ticked as Style"
               + (f" - only the first {MAX_FILES} (alphabetical) are used." if len(style_files) > MAX_FILES else "."))
    quick = st.checkbox("Quick analysis (rule-based, no AI cost)", value=bool(s.cre_demo_mode),
                        disabled=bool(s.cre_demo_mode), key="style-quick",
                        help="Demo mode always uses the rule-based analysis. The AI analysis captures style far better.")
    if st.button("Learn style from these reports", key="style-learn", type="primary", disabled=not style_files):
        try:
            with st.spinner("Analysing the example reports..."):
                learned = learn_profile(use_llm=not quick)
            if not quick and learned.method != "llm":
                # learn_profile falls back to the heuristic when the AI call fails (logged).
                _notice("warning", "The AI analysis failed, so the rule-based analysis was used. See the log.")
            else:
                _notice("success", f"Learned: {learned.name} ({learned.method}).")
            st.rerun()
        except ValueError as exc:  # no usable examples (e.g. scanned PDFs): a user problem, not a bug
            st.error(str(exc))
        except Exception as exc:  # noqa: BLE001 - show a reference, not a traceback
            _incident(exc, "style")


# --------------------------------------------------------------------------
# Performance check
# --------------------------------------------------------------------------

def _fmt(v, suffix: str = "%") -> str:
    return "–" if v is None else f"{v:g}{suffix}"


def answer_key_section(report: str):
    """Build / moderate the answer key. Returns the key (or None)."""
    from cre_monitor.authoring import NeedsLiveMode
    from cre_monitor.benchmark import answer_key as ak
    from cre_monitor.catalog import get_catalog

    key = ak.load_key(report)
    st.markdown("**1 · Answer key** - the figures this report states, as the right answers")
    build_label = "Rebuild answer key" if key else "Build answer key with Claude"
    if st.button(build_label, key="bench-build", type="secondary" if key else "primary",
                 help="One Claude call (skill model, a few cents). Rebuilding replaces your moderation."):
        try:
            with st.spinner("Extracting figures and themes..."):
                ak.save_key(ak.build_key(report))
            _notice("success", "Answer key built. Review it below - only accepted figures are scored.")
            st.rerun()
        except NeedsLiveMode as exc:
            st.warning(str(exc))
        except ValueError as exc:
            st.error(str(exc))
        except Exception as exc:  # noqa: BLE001
            _incident(exc, "bench-key")
    if key is None:
        return None

    stats = key.stats()
    c = st.columns(5)
    c[0].metric("Figures", stats["total"])
    c[1].metric("In the document", f"{stats['in_document']}/{stats['total']}",
                help="The value really appears in the report text (any formatting).")
    c[2].metric("Safe", stats["safe"], help="In the document, known metric/unit/place, period parses, "
                                          f"AI confidence ≥ {ak.SAFE_CONFIDENCE}.")
    c[3].metric("Accepted", stats["accepted"], help="Only accepted figures are scored.")
    c[4].metric("Pending", stats["pending"])
    if st.button(f"Accept all safe ({sum(e.safe and e.status == 'pending' for e in key.entries)})",
                 key="bench-accept-safe"):
        n = key.accept_safe()
        ak.save_key(key)
        _notice("success", f"Accepted {n} safe figure(s).")
        st.rerun()

    cat = get_catalog()
    risky_first = sorted(key.entries, key=lambda e: (e.safe, e.confidence))
    table = pd.DataFrame([{
        "id": e.id, "status": e.status, "metric": cat.label(e.key), "submarket": e.submarket, "period": e.period,
        "value": e.value, "unit": e.unit, "source": e.source, "in doc": e.in_document,
        "confidence": round(e.confidence, 2), "catalogue": e.catalogue_match, "period ok": e.period_ok,
        "safe": e.safe, "citation": e.citation} for e in risky_first])
    st.caption("Riskiest first. Edit **status**, **value**, **period** or **submarket**, then save. "
               "Signals are recomputed on save.")
    edited = st.data_editor(
        table, key=f"bench-editor-{report}", hide_index=True, width="stretch",
        disabled=[c for c in table.columns if c not in ("status", "value", "period", "submarket")],
        column_config={"id": None,
                       "status": st.column_config.SelectboxColumn(options=["pending", "accepted", "rejected"]),
                       "citation": st.column_config.LinkColumn()})
    if st.button("Save moderation", key="bench-save-mod"):
        try:
            n = ak.apply_edits(key, edited.to_dict("records"), ak.report_text(report))
            ak.save_key(key)
            _notice("success", f"Saved ({n} figure(s) changed).")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    with st.expander(f"Key themes ({len(key.themes)}) - used by the brief judge"):
        st.markdown("\n".join(f"- {t}" for t in key.themes) or "None.")
    return key


def figure_run_section(key) -> None:
    from cre_monitor.authoring import NeedsLiveMode
    from cre_monitor.benchmark.runner import plan_run, run_figures

    st.markdown("**2 · Figure run** - can the agent find these figures itself?")
    plan = plan_run(key)
    s = get_settings()
    if not key.accepted():
        st.caption("Accept at least one figure first.")
        return
    st.caption(f"Runs **{', '.join(plan.groups) or 'no skill'}** (only the skills that collect the accepted "
               f"figures), for period {key.period or 'as stated'}. Estimated **~${plan.estimate_usd:.2f}** "
               f"(target under ${s.benchmark_target_usd:.2f}; the actual estimate is recorded)."
               + (f" {len(plan.not_collectable)} figure(s) are not collected by any skill and count as missing."
                  if plan.not_collectable else ""))
    hints = st.checkbox("Give the agent the report's publisher and citations as leads", value=True,
                        key="bench-hints", help="On: tests following up the report's citations. Off: tests finding "
                                                "the figures from scratch (harder).")
    if st.button("Run performance check", key="bench-run", type="primary"):
        try:
            with st.spinner(f"Running {len(plan.groups)} skill(s)..."):
                run_figures(key, hints=hints)
            _notice("success", "Performance run finished - see the scorecard below.")
            st.rerun()
        except NeedsLiveMode as exc:
            st.warning(str(exc))
        except Exception as exc:  # noqa: BLE001
            _incident(exc, "bench-run")


def judge_section(key) -> None:
    from cre_monitor.benchmark.runner import run_judge
    from cre_monitor.reporting.briefs import list_briefs

    st.markdown("**3 · Brief judgement** - how does an existing brief compare with this report?")
    briefs = list_briefs()
    if not briefs:
        st.caption("No briefs yet - run one from the sidebar first.")
        return
    labels = {b.run_id: b.label for b in briefs}
    brief = st.selectbox("Brief", list(labels), format_func=labels.get, key="bench-brief")
    st.caption("Readability and the citation check are free; the rubric is one Claude call (live mode).")
    if st.button("Judge brief", key="bench-judge"):
        try:
            with st.spinner("Judging..."):
                run_judge(key, brief)
            _notice("success", "Judgement finished - see the scorecard below.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
        except Exception as exc:  # noqa: BLE001
            _incident(exc, "bench-judge")


def show_figure_run(rec, key) -> None:
    from cre_monitor.catalog import get_catalog

    f, c = rec.figure, rec.citation
    st.markdown(f"**Latest figure run** · {rec.created_at:%d %b %Y %H:%M} · skills: {', '.join(rec.skills)}"
                f" · {'with' if rec.hints else 'without'} citation leads")
    t = st.columns(6)
    t[0].metric("Coverage", _fmt(f.get("coverage")), help="Accepted figures the agent returned (same metric, "
                                                          "submarket, period).")
    t[1].metric("Accuracy", _fmt(f.get("accuracy")), help="Of figures found: within tolerance "
                                                          "(±0.1pp for rates, ±2% otherwise).")
    t[2].metric("Same-source accuracy", _fmt(f.get("accuracy_same_source")),
                help="Accuracy where the agent used the same publisher as the report (like-for-like).")
    t[3].metric("Grounding", _fmt(f.get("grounding")), help="Agent figures that appear in what its tools returned. "
                                                            "Below 100% = possibly made up.")
    t[4].metric("Citations contain figure", _fmt(c.get("pct_contains")),
                help=f"Of cited pages that opened. {c.get('unverifiable', 0)} unverifiable (blocked/paywalled).")
    t[5].metric("Est. cost", f"${rec.cost_usd:.2f}", help=f"{rec.tokens_in:,} in / {rec.tokens_out:,} out tokens, "
                                                         f"{rec.duration_s:.0f}s. Estimate from the price table.")
    for w in rec.warnings:
        st.warning(w)
    cat = get_catalog()
    entries = {e.id: e for e in key.entries}
    cites = {(x["key"], x["submarket"], x["value"]): x["status"] for x in rec.citations}
    rows = []
    for r in rec.entries:
        e = entries.get(r["entry_id"])
        rows.append({
            "metric": cat.label(e.key) if e else r["entry_id"], "submarket": e.submarket if e else "",
            "period": e.period if e else "", "expected": r["expected"], "found": r["found"], "result": r["status"],
            "same source": r["same_source"] if r["found"] is not None else None, "found source": r["found_source"],
            "error %": r["pct_error"], "grounded": r["grounded"],
            "citation": cites.get((e.key, e.submarket, r["found"])) if e and r["found"] is not None else None})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def show_judge_run(rec) -> None:
    st.markdown(f"**Latest brief judgement** · brief {rec.brief_run_id} · {rec.created_at:%d %b %Y %H:%M}")
    j = rec.judgement
    if j:
        t = st.columns(5)
        t[0].metric("Theme coverage", _fmt(j.get("theme_coverage")))
        for col, name in zip(t[1:], ("consistency", "so_what", "structure", "readability")):
            col.metric(name.replace("_", "-").capitalize(), f"{j[name]['score']}/5", help=j[name]["reason"])
        st.caption(j.get("summary", ""))
        st.dataframe(pd.DataFrame(j["themes"]), hide_index=True, width="stretch")
        for x in j.get("contradictions", []):
            st.error(f"Contradiction: {x}")
    for w in rec.warnings:
        st.warning(w)
    rb, rr = rec.readability_brief, rec.readability_reference
    labels = {"flesch": "Flesch reading ease (higher = easier)", "avg_sentence_words": "Avg sentence (words)",
              "pct_long_sentences": "Sentences > 30 words (%)", "pct_figures_with_period": "Figures with a period (%)"}
    st.dataframe(pd.DataFrame([{"measure": lab, "brief": rb.get(k), "reference": rr.get(k)}
                               for k, lab in labels.items()]), hide_index=True, width="stretch")
    c = rec.citation
    st.caption(f"Brief citations: {c.get('pct_contains', '–')}% of opened pages contain the figure · "
               f"{c.get('unverifiable', 0)} unverifiable · {c.get('no_url', 0)} without a link · "
               f"est. cost ${rec.cost_usd:.2f}")


def history_section(report: str) -> None:
    from cre_monitor.benchmark.store import list_runs

    runs = list_runs(report)
    with st.expander(f"History ({len(runs)} run(s))"):
        if not runs:
            st.caption("No runs yet.")
            return
        df = pd.DataFrame([{
            "when": r.created_at, "kind": r.kind, "coverage %": r.figure.get("coverage"),
            "accuracy %": r.figure.get("accuracy"), "grounding %": r.figure.get("grounding"),
            "citations %": r.citation.get("pct_contains"),
            "themes %": (r.judgement or {}).get("theme_coverage"), "est. $": r.cost_usd} for r in runs])
        figs = df[df["kind"] == "figures"].set_index("when")[["coverage %", "accuracy %", "grounding %"]]
        if len(figs) >= 2:
            st.line_chart(figs.sort_index())
        st.dataframe(df, hide_index=True, width="stretch")


def performance_check() -> None:
    from cre_monitor.benchmark.store import list_runs
    from cre_monitor.style import examples_with_role

    st.caption("Measures whether the agent's research is **right**, against reports you trust: the figures it "
               "finds (coverage, accuracy, made-up numbers, citations) and how a brief compares (themes, "
               "readability). Definitions: docs/EVALUATION.md.")
    reports = [p.name for p in examples_with_role("benchmark")]
    if not reports:
        st.info("Tick **Benchmark** for at least one report in the library above.")
        return
    report = st.selectbox("Reference report", reports, key="bench-report")
    key = answer_key_section(report)
    if key is None:
        return
    st.divider()
    figure_run_section(key)
    st.divider()
    judge_section(key)
    st.divider()
    if fig := next(iter(list_runs(report, "figures")), None):
        show_figure_run(fig, key)
    if jud := next(iter(list_runs(report, "judge")), None):
        show_judge_run(jud)
    history_section(report)


def reference_tab() -> None:
    _show_notice()
    with st.expander("📁 Library", expanded=True):
        library()
    t_style, t_perf = st.tabs(["🎨 House style", "🎯 Performance check"])
    with t_style:
        house_style()
    with t_perf:
        performance_check()
