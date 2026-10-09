"""Dashboard > Metrics > "Add a metric": describe it, Claude checks feasibility, you approve.

Flow (state kept in ``st.session_state.metric_assessment`` between reruns):

1. The user describes the metric in plain English.
2. :func:`cre_monitor.authoring.assess_metric` returns a verdict
   (exact catalogue matches are recognised without Claude):

   * **Already collected** -> "Track it".
   * **Collectable with a skill change** -> an editable proposal (name, unit,
     definition, plausible range, which skill, the guidance added to it). The
     panel lists exactly what will change. **Approve and apply** writes the
     catalogue entry and the skill change (both with version history).
   * **Not feasible with the current tools** -> why, and what a developer would
     need to add. Nothing changes.
3. Optionally **Test now** runs the skill once (live mode; costs one research
   run) and shows whether the figure came back.
"""

from __future__ import annotations

import streamlit as st

from cre_monitor.catalog import GROUP_ORDER
from cre_monitor.ui.components import render_incident

#: Metric groups offered (the catalogue's display order, plus a catch-all).
GROUPS = [*GROUP_ORDER, "Other"]


def _assessment():
    from cre_monitor.authoring import MetricAssessment

    data = st.session_state.get("metric_assessment")
    return MetricAssessment.model_validate(data) if data else None


def _clear() -> None:
    for k in [k for k in st.session_state if str(k).startswith("am-")] + ["metric_assessment"]:
        st.session_state.pop(k, None)


def add_metric_panel() -> None:
    from cre_monitor.authoring import NeedsLiveMode, assess_metric

    st.markdown("**➕ Add a metric**")
    st.caption("Describe the figure you want to follow. Claude checks whether the research skills can find it in "
               "public sources and proposes what would change. **Nothing is saved until you approve.**")
    if done := st.session_state.pop("metric_applied_msg", None):
        st.success(done)
    request = st.text_input("What should be tracked?", key="metric-request",
                            placeholder="e.g. Average lease length for new City lettings")
    if st.button("Check feasibility", type="primary", key="metric-assess", disabled=not request.strip()):
        _clear()
        for k in ("metric_test", "metric_last_applied"):
            st.session_state.pop(k, None)
        try:
            with st.spinner("Checking the catalogue, skills and public sources..."):
                st.session_state.metric_assessment = assess_metric(request).model_dump()
        except NeedsLiveMode as exc:
            st.warning(f"{exc} Exact names of existing metrics still work, e.g. 'Prime yield'.")
        except Exception as exc:  # noqa: BLE001 - show a reference, not a traceback
            from cre_monitor.errors import incident_from_exception

            render_incident(incident_from_exception(exc, step="assess-metric"))
    if (a := _assessment()) is not None:
        show_assessment(a)
    else:
        test_panel()
        if tested := st.session_state.get("metric_test"):
            show_test(*tested)


def show_assessment(a) -> None:
    from cre_monitor.authoring import apply_assessment
    from cre_monitor.catalog import get_catalog

    cat = get_catalog()
    if a.verdict == "already_collected":
        m = cat.metric(a.existing_key)
        st.success(f"**Already collected:** {m.label} ({m.unit}). {a.reasoning}", icon="✅")
        if m.tracked:
            st.info("It is already tracked - see the Overview tab.")
        elif st.button("Track it", type="primary", key="am-track"):
            st.session_state.metric_applied_msg = apply_assessment(a)
            _clear()
            st.rerun()
        return

    if a.verdict == "not_feasible":
        st.warning(f"**Not possible with the current tools.** {a.reasoning}", icon="🚧")
        if a.developer_changes:
            st.markdown(f"**What a developer would need to add:** {a.developer_changes}")
        if a.likely_sources:
            st.caption("Where it is published: " + "; ".join(a.likely_sources))
        if st.button("Discard", key="am-discard"):
            _clear()
            st.rerun()
        return

    # needs_skill_change: editable proposal.
    from cre_monitor.skills.registry import get_registry

    st.info(f"**Can be collected** by updating the **{a.target_skill}** skill. {a.reasoning}", icon="🛠️")
    if a.likely_sources:
        st.caption("Published by: " + "; ".join(a.likely_sources))
    c1, c2 = st.columns(2)
    label = c1.text_input("Name", a.label, key="am-label")
    key = c2.text_input("Key (stored with every figure)", a.key, key="am-key")
    unit = c1.text_input("Unit", a.unit, key="am-unit", help="e.g. years, %, GBP psf pa, sq ft")
    group = c2.selectbox("Group", GROUPS, index=GROUPS.index(a.group) if a.group in GROUPS else len(GROUPS) - 1,
                         key="am-group")
    definition = st.text_input("Definition", a.definition, key="am-def")
    research = [s.name for s in get_registry().research_skills()]
    skill = c1.selectbox("Skill that collects it", research,
                         index=research.index(a.target_skill) if a.target_skill in research else 0, key="am-skill")
    lo = c2.number_input("Plausible minimum", value=a.sanity_min, key="am-min",
                         help="Figures outside the range are treated as mis-reads and dropped.")
    hi = c2.number_input("Plausible maximum", value=a.sanity_max, key="am-max")
    guidance = st.text_area("Guidance added to the skill (where to find it, how to record it)", a.guidance,
                            height=140, key="am-guidance")
    domains = st.text_input("Preferred websites (comma-separated)", ", ".join(a.preferred_domains), key="am-domains")

    st.markdown("**What will change**")
    st.markdown(
        f"- `catalog/metrics.yaml`: new metric **{label}** (`{key}`, {unit}), tracked on the Dashboard\n"
        f"- `skills/{skill}/SKILL.md`: collects `{key}`"
        + (f", plausible range {lo:g}-{hi:g}" if lo is not None and hi is not None else "")
        + ", plus an *Additional metrics* section with the guidance above"
        + (f", preferred websites {domains}" if domains.strip() else "") + "\n"
        "- Both files keep their previous version (restorable). Commit them to git to share with the team.")
    b1, b2 = st.columns(2)
    if b1.button("Approve and apply", type="primary", key="am-apply"):
        final = a.model_copy(update={
            "label": label.strip(), "key": key.strip(), "unit": unit.strip(), "group": group,
            "definition": definition.strip(), "target_skill": skill, "sanity_min": lo, "sanity_max": hi,
            "guidance": guidance, "preferred_domains": [d.strip() for d in domains.split(",") if d.strip()]})
        try:
            msg = apply_assessment(final)
        except ValueError as exc:  # invalid key, duplicate name, etc.
            st.error(str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            from cre_monitor.errors import incident_from_exception

            render_incident(incident_from_exception(exc, step="apply-metric"))
            return
        st.session_state.metric_applied_msg = msg
        st.session_state.metric_last_applied = final.model_dump()
        _clear()
        st.rerun()
    if b2.button("Discard", key="am-discard"):
        _clear()
        st.rerun()


def test_panel() -> None:
    """'Test now' for the metric added last (live mode only)."""
    from cre_monitor.authoring import MetricAssessment, NeedsLiveMode, test_metric

    data = st.session_state.get("metric_last_applied")
    if not data:
        return
    a = MetricAssessment.model_validate(data)
    st.caption(f"Test **{a.label}** now: runs the {a.target_skill} skill once (live mode, a few cents to "
               "~$0.50) and shows whether the figure comes back.")
    if st.button("🧪 Test now", key="metric-test"):
        try:
            with st.spinner(f"Running {a.target_skill}..."):
                found, finding = test_metric(a)
            st.session_state.metric_test = (a.model_dump(), found, finding.model_dump())
        except NeedsLiveMode as exc:
            st.warning(str(exc))
        st.rerun()


def show_test(a_data: dict, found: bool, finding_data: dict) -> None:
    from cre_monitor.schemas import SkillFinding

    finding = SkillFinding.model_validate(finding_data)
    key = a_data.get("existing_key") or a_data.get("key")
    if finding.error:
        st.error(f"The test run failed: {finding.error}")
    elif found:
        rows = [f"- {m.submarket} {m.period}: {m.value:g} {m.unit} ({m.source})" for m in finding.metrics if m.key == key]
        st.success("**Found it.** The skill returned:\n" + "\n".join(rows))
    else:
        st.warning("The skill ran but didn't return this figure. Try more specific guidance (where exactly it is "
                   "published) in the skill, or check that public sources report it.")
