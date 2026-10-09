"""🧩 Skills tab: view, edit, add, delete and restore research skills without touching files.

Backed by :mod:`cre_monitor.skills.editor` (validation, version history,
conflict check, soft delete) and :mod:`cre_monitor.authoring` (Claude drafts a
new skill / reviews a draft). Layout:

* a picker with every skill, plus **➕ New skill**;
* for an existing skill: a form with the essentials (description, tools,
  metrics, whether it is researched in every brief, instructions) and a
  collapsed **Advanced settings** section for rarely changed fields (plausible
  ranges, preferred websites, trigger words, report position, model); then
  **Validate**, **Check with Claude**, **Save**; a **Test run**; earlier versions
  with **Restore**; **Delete** (to the trash);
* for a new skill: name + what it should research, then **Draft with Claude**
  (live) or **Start from a blank template**, then the same form;
* **Deleted skills** with **Restore** at the bottom.

Saved skills apply to the next brief or chat question. The files are tracked in
git; a banner lists UI changes not yet committed so the team can review them.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from cre_monitor.skills.editor import PROTECTED_SKILLS, TOOL_LABELS, SkillDraft
from cre_monitor.ui.components import render_incident

NEW = "➕ New skill"
#: The in_brief switch, phrased by its effect (the frontmatter field is `in_brief`).
BRIEF_LABEL = "Research this topic in every market brief (not only when asked in chat)"
#: Model tiers (config.py) in plain English, for the Advanced settings.
TIERS = {
    "skill": "Standard (Sonnet) - recommended",
    "synthesis": "Strongest (Opus) - slower, costs more",
    "router": "Fastest (Haiku) - cheapest, weaker research",
}
BLANK_INSTRUCTIONS = """# <Topic>

## Goal
What this skill must establish, for whom, and how current it must be.

## Definitions (be precise - brokers differ)
- **Term**: exact meaning, unit, what is included / excluded.

## Method
1. Search for ... e.g. `"<broker> London office <topic> Q3 2026"`.
2. Read at least one primary source with `fetch_document`.
3. Compare with our history (`metrics_history`) and describe the trend.

## Interpreting
What the evidence means for a London office landlord / investor / developer (risks, opportunities).

## Output guidance
- One metric per submarket per source, with `period` = quarter (e.g. 2026-Q3).
"""


def _flash(kind: str, text: str) -> None:
    st.session_state.skills_flash = (kind, text)


def _reset_form(prefix: str) -> None:
    """Forget widget values so the form shows the file's current content."""
    for k in [k for k in st.session_state if str(k).startswith(prefix)]:
        del st.session_state[k]


# --------------------------------------------------------------------------
# The form shared by "edit" and "new"
# --------------------------------------------------------------------------

def draft_form(draft: SkillDraft, prefix: str, *, is_new: bool, version: str | None) -> None:
    """Editable form for ``draft``; handles Validate / Check with Claude / Save."""
    from cre_monitor.catalog import get_catalog
    from cre_monitor.tools import TOOL_NAMES

    cat = get_catalog()
    metric_keys = [m.key for m in cat.metrics]
    with st.form(f"{prefix}form"):
        description = st.text_area(
            "Description - what it researches and **when** to use it", draft.description, height=90,
            key=f"{prefix}desc", help="The router reads only this text to decide whether to run the skill for a question.")
        c1, c2 = st.columns(2)
        tools = c1.multiselect("Research tools it may use", list(TOOL_NAMES), default=[t for t in draft.tools
                               if t in TOOL_NAMES], format_func=lambda t: TOOL_LABELS.get(t, t), key=f"{prefix}tools",
                               help="New data sources need a developer.")
        metrics = c2.multiselect("Metrics it must record", metric_keys, default=[m for m in draft.metrics
                                 if m in metric_keys], format_func=lambda k: f"{cat.label(k)} ({cat.units()[k]})",
                                 key=f"{prefix}metrics", help="Add new metrics in Dashboard > Metrics first.")
        in_brief = st.checkbox(
            BRIEF_LABEL, draft.in_brief, key=f"{prefix}brief",
            help="**Ticked**: researched in every full market brief - the scheduled weekly brief and "
                 "*Run full brief now* - and listed in the sidebar's partial-brief tick boxes. Each brief then "
                 "includes a section on this topic, and costs one more research run (a few cents to ~$0.50).\n\n"
                 "**Unticked**: on demand only - researched when a chat question needs it (or with *Test run*). "
                 "Good for niche topics, or for a new skill you are still refining.")
        instructions = st.text_area("Instructions (Markdown) - what the research agent is told", draft.instructions,
                                    height=380, key=f"{prefix}instr")

        # Rarely changed: sensible defaults are set for new skills (and by "Draft with Claude").
        # The values are always saved as shown, so collapsing this section never loses them.
        with st.expander("⚙️ Advanced settings - usually no need to change"):
            ranges = pd.DataFrame([{"metric": k, "min": lo, "max": hi} for k, (lo, hi) in draft.sanity_ranges.items()],
                                  columns=["metric", "min", "max"])
            st.caption("**Plausible ranges** - a safety net: figures outside them are treated as mis-reads "
                       "(e.g. 85% vacancy) and dropped.")
            ranges = st.data_editor(
                ranges, num_rows="dynamic", hide_index=True, key=f"{prefix}ranges", width="stretch",
                column_config={"metric": st.column_config.SelectboxColumn("Metric", options=metric_keys, required=True),
                               "min": st.column_config.NumberColumn("Min", required=True),
                               "max": st.column_config.NumberColumn("Max", required=True)})
            a1, a2 = st.columns(2)
            domains = a1.text_input("Preferred websites (comma-separated)", ", ".join(draft.preferred_domains),
                                    key=f"{prefix}domains", help="Sources the research agent should look at first.")
            keywords = a2.text_input("Trigger words (comma-separated)", ", ".join(draft.keywords),
                                     key=f"{prefix}keywords",
                                     help="Used to route chat questions to this skill when Claude is unavailable.")
            order = a1.number_input("Position in the report", value=int(draft.order), step=10, key=f"{prefix}order",
                                    help="Order of the topic sections in the brief: lower numbers come first "
                                         "(built-in topics use 10-80; new skills start at 200, i.e. at the end). "
                                         "Equal numbers are fine - they are then ordered alphabetically.")
            tier = a2.selectbox("Model", list(TIERS), index=list(TIERS).index(draft.model_tier)
                                if draft.model_tier in TIERS else 0, format_func=TIERS.get, key=f"{prefix}tier",
                                help="Which Claude model researches this topic. Keep the standard model unless "
                                     "the performance check shows a reason to change.")
        b1, b2, b3 = st.columns(3)
        do_validate = b1.form_submit_button("✅ Validate", width="stretch")
        do_review = b2.form_submit_button("🔍 Check with Claude", width="stretch",
                                          help="Claude reviews clarity, overlap with other skills and metric guidance.")
        do_save = b3.form_submit_button("💾 Create skill" if is_new else "💾 Save", type="primary", width="stretch")

    if not (do_validate or do_review or do_save):
        return
    rows = ranges.dropna() if isinstance(ranges, pd.DataFrame) else pd.DataFrame()
    new = SkillDraft(
        name=draft.name, description=description.strip(), tools=tools, metrics=metrics,
        sanity_ranges={r["metric"]: (min(r["min"], r["max"]), max(r["min"], r["max"])) for _, r in rows.iterrows()},
        preferred_domains=[d.strip() for d in domains.split(",") if d.strip()],
        keywords=[k.strip().lower() for k in keywords.split(",") if k.strip()],
        in_brief=in_brief, order=int(order), model_tier=tier, instructions=instructions)
    _act(new, prefix, is_new=is_new, version=version, review=do_review, save=do_save)


def _act(draft: SkillDraft, prefix: str, *, is_new: bool, version: str | None, review: bool, save: bool) -> None:
    from cre_monitor.authoring import NeedsLiveMode, review_skill
    from cre_monitor.skills.editor import save_skill, validate_draft
    from cre_monitor.versioned import ConflictError

    problems = validate_draft(draft, is_new=is_new)
    if problems:
        st.error("Please fix:\n" + "\n".join(f"- {p}" for p in problems))
        return
    if not save:
        st.success("No problems found - the skill will load.")
    if review:
        try:
            with st.spinner("Claude is reviewing the skill..."):
                r = review_skill(draft)
            (st.success if r.ok else st.warning)(
                f"**{'Looks good' if r.ok else 'Needs changes'}:** {r.summary}"
                + "".join(f"\n- ⚠ {i}" for i in r.issues) + "".join(f"\n- 💡 {s}" for s in r.suggestions))
        except NeedsLiveMode as exc:
            st.info(str(exc))
        except Exception as exc:  # noqa: BLE001
            from cre_monitor.errors import incident_from_exception

            render_incident(incident_from_exception(exc, step="review-skill"))
    if save:
        try:
            save_skill(draft, is_new=is_new, expected_version=version)
        except ConflictError as exc:
            st.error(f"{exc}  Click **Reload** to see their version.")
            return
        except ValueError as exc:
            st.error(str(exc))
            return
        _reset_form(prefix)
        if is_new:
            st.session_state.pop("new_skill_draft", None)
            st.session_state.skill_select_next = draft.name   # applied before the picker is drawn
        _flash("success", f"Saved **{draft.name}**. It applies to the next brief or question.")
        st.rerun()


# --------------------------------------------------------------------------
# Existing skill
# --------------------------------------------------------------------------

def edit_skill(name: str) -> None:
    from cre_monitor.skills import editor
    from cre_monitor.versioned import version_label

    # ":" cannot occur in skill names, so one skill's prefix never matches another's
    # (with "-", clearing skill "news" would also clear "news-events").
    prefix = f"sk:{name}:"
    draft, current_version = editor.load_draft(name)
    # The version the form was opened at: a save is refused if the file changed since.
    version = st.session_state.setdefault(f"{prefix}version", current_version)
    if version != current_version:
        st.warning("This skill was changed (by someone else, or by restoring a version) since you opened it.")
        if st.button("Reload", key=f"{prefix}reload"):
            _reset_form(prefix)
            st.rerun()
    if name in PROTECTED_SKILLS:
        st.caption("🔒 Used by the summary step: it can be edited but not deleted. It has no research tools.")
    draft_form(draft, prefix, is_new=False, version=version)

    c1, c2, c3 = st.columns(3)
    with c1.popover("🧪 Test run", width="stretch"):
        st.caption("Runs this skill once as in a brief and shows what it found. Live mode costs one research "
                   "run (a few cents to ~$0.50); demo mode shows the canned finding.")
        if st.button("Run now", key=f"{prefix}test", type="primary"):
            from cre_monitor.graph.nodes.planner import BRIEF_TASK
            from cre_monitor.graph.nodes.skill_runner import run_skill

            with st.spinner(f"Running {name}..."):
                finding = run_skill(name, BRIEF_TASK)
            if finding.error:
                st.error(f"Failed: {finding.error}")
            else:
                st.markdown(f"**{finding.headline}**\n\n{finding.summary}")
                for m in finding.metrics:
                    st.caption(f"{m.key} · {m.submarket} · {m.period}: {m.value:g} {m.unit} ({m.source})")
    with c2.popover("🕘 Earlier versions", width="stretch"):
        versions = editor.versions(name)
        if not versions:
            st.caption("No earlier versions saved from the UI yet.")
        for i, v in enumerate(versions[:15]):
            vc1, vc2 = st.columns([0.7, 0.3], vertical_alignment="center")
            vc1.caption(version_label(v))
            if vc2.button("Restore", key=f"{prefix}restore-{i}"):
                editor.restore_version(name, v)
                _reset_form(prefix)
                _flash("success", f"Restored the version from {version_label(v)}.")
                st.rerun()
    if name not in PROTECTED_SKILLS:
        with c3.popover("🗑 Delete", width="stretch"):
            orphaned = editor.orphaned_metrics(name)
            st.markdown(f"Delete **{name}**?")
            st.caption("It moves to *Deleted skills* below and can be restored."
                       + (f" No other skill collects: {', '.join(orphaned)}." if orphaned else ""))
            if st.button("Delete", type="primary", key=f"{prefix}delete"):
                editor.delete_skill(name)
                _reset_form(prefix)
                st.session_state.pop("skill-select", None)
                _flash("success", f"Deleted **{name}** (restorable under Deleted skills).")
                st.rerun()


# --------------------------------------------------------------------------
# New skill
# --------------------------------------------------------------------------

def new_skill() -> None:
    from cre_monitor.authoring import NeedsLiveMode, draft_skill

    st.caption("Give the skill a short name and describe what it should research. Claude can draft the whole skill "
               "(definitions, method, metrics) for you to review, or start from a blank template.")
    c1, c2 = st.columns([1, 2])
    name = c1.text_input("Name", key="new-name", placeholder="e.g. lease-events",
                         help="Lower-case words joined by hyphens.").strip().lower().replace(" ", "-")
    purpose = c2.text_input("What should it research?", key="new-purpose",
                            placeholder="e.g. Upcoming lease expiries and break options in central London offices")
    b1, b2 = st.columns(2)
    if b1.button("✨ Draft with Claude", type="primary", key="new-draft", disabled=not (name and purpose)):
        try:
            with st.spinner("Claude is drafting the skill..."):
                draft, notes = draft_skill(name, purpose)
            st.session_state.new_skill_draft = (draft.model_dump(), notes)
            _reset_form("sk+new:")
        except NeedsLiveMode as exc:
            st.info(f"{exc} Use the blank template instead.")
        except Exception as exc:  # noqa: BLE001
            from cre_monitor.errors import incident_from_exception

            render_incident(incident_from_exception(exc, step="draft-skill"))
    if b2.button("Start from a blank template", key="new-blank", disabled=not name):
        st.session_state.new_skill_draft = (SkillDraft(
            name=name, description=purpose or "", tools=["web_search", "fetch_document"], order=200,
            instructions=BLANK_INSTRUCTIONS).model_dump(), [])
        _reset_form("sk+new:")
    if saved := st.session_state.get("new_skill_draft"):
        data, notes = saved
        for n in notes:
            st.info(n)
        draft = SkillDraft.model_validate(data | {"name": name or data["name"]})
        draft_form(draft, "sk+new:", is_new=True, version=None)


# --------------------------------------------------------------------------
# Tab
# --------------------------------------------------------------------------

def skills_tab() -> None:
    from cre_monitor.skills import editor
    from cre_monitor.skills.registry import get_registry

    if flash := st.session_state.pop("skills_flash", None):
        kind, text = flash
        (st.error if kind == "error" else st.success)(text)
    st.caption("Skills are the research topics the agent covers. Each has plain-English instructions, the tools it "
               "may use and the metrics it records. Changes apply to the next brief or chat question.")
    if changes := editor.git_changes():
        st.info("**Not yet committed to git** (the rest of the team won't see these until a developer commits "
                "them):\n" + "\n".join(f"- `{c}`" for c in changes[:20]), icon="📝")
    reg = get_registry()
    for folder, err in reg.errors.items():
        st.error(f"Skill **{folder}** could not be loaded and is skipped: {err}")

    names = [s.name for s in reg.all()]
    if (nxt := st.session_state.pop("skill_select_next", None)) in names:
        st.session_state["skill-select"] = nxt
    if st.session_state.get("skill-select") not in [NEW, *names]:
        # First visit, or the selected skill was deleted: open the first skill. (Set via session
        # state only - passing index= as well makes Streamlit warn.)
        st.session_state["skill-select"] = names[0] if names else NEW
    def _status(meta) -> str:
        if not meta.tools:
            return "writes the brief's summary"      # meta-skill (market-synthesis)
        return "in every brief" if meta.in_brief else "on demand (chat only)"

    labels = {n: f"{n}  ·  {_status(reg.get(n).meta)}" for n in names}
    choice = st.selectbox("Skill", [NEW, *names], key="skill-select", format_func=lambda n: labels.get(n, n))
    if choice == NEW:
        new_skill()
    else:
        st.caption(reg.get(choice).meta.description)
        edit_skill(choice)

    trash = editor.list_trash()
    with st.expander(f"🗑 Deleted skills ({len(trash)})"):
        if not trash:
            st.caption("Nothing here.")
        for trash_id, name, when in trash:
            c1, c2 = st.columns([0.75, 0.25], vertical_alignment="center")
            c1.markdown(f"**{name}** - deleted {when}")
            if c2.button("Restore", key=f"restore-{trash_id}"):
                try:
                    editor.restore_skill(trash_id)
                    _flash("success", f"Restored **{name}**.")
                except ValueError as exc:
                    _flash("error", str(exc))
                st.rerun()
