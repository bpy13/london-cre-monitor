# Contributing without code: skills, metrics and submarkets in the web UI

For analysts and colleagues who want to shape what the agent researches without editing files.
Everything here happens in the web UI (`cre-monitor ui`). Developers: the same changes can be made
by editing the files directly; see [SKILLS.md](SKILLS.md) and [DATA_MODEL.md](DATA_MODEL.md).

## The three building blocks

| Block | What it is | Where in the UI | File |
|---|---|---|---|
| **Skill** | A research topic: instructions the research agent follows, the tools it may use, the metrics it must record | 🧩 Skills tab | `skills/<name>/SKILL.md` |
| **Metric** | A figure the agent records, with a fixed unit and definition (e.g. prime rent, £ psf pa) | Dashboard → ⚙️ Metrics | `catalog/metrics.yaml` |
| **Submarket** | A place figures are recorded against (e.g. City), with aliases brokers use | Dashboard → 📍 Submarkets | `catalog/submarkets.yaml` |

A metric is only collected if some skill lists it, and a skill may only list metrics that are
in the catalogue. That is why adding a metric can also change a skill.

## Common tasks

**Follow a new figure on the Dashboard**
1. Dashboard → ⚙️ Metrics → ➕ Add a metric. Describe it precisely: what, where, how often.
2. Read the verdict. If it **can be collected**, check the proposal: is the definition right? Is
   the plausible range sensible? Is it the right skill? Then **Approve and apply**.
3. **🧪 Test now** (live mode) to see whether the skill finds it. If not, sharpen the guidance
   in the Skills tab: name the publisher and report where it appears.

**Stop following a figure**: untick it under ⚙️ Metrics (its history is kept). Use 🗑 only if
nobody needs it any more.

**Improve how a topic is researched**: 🧩 Skills → pick the skill → edit the instructions (be
specific: definitions, which reports, example searches) → ✅ Validate → 🔍 Check with Claude
→ 💾 Save → 🧪 Test run.

**Add a new research topic**: 🧩 Skills → ➕ New skill → short name (e.g. `lease-events`) and
one sentence on what it should research → ✨ Draft with Claude → review the fields →
decide whether it should be **researched in every market brief** or stay on demand (chat only)
→ 💾 Create skill. If Claude says metrics are missing, add them first (Dashboard → ⚙️ Metrics),
then tick them in the skill. The **⚙️ Advanced settings** (plausible ranges, report position,
model, …) come pre-filled; you rarely need to open them.

**Add a submarket**: Dashboard → 📍 Submarkets → Add, with aliases (other spellings brokers use).

**Check whether a change made the agent better**: 📚 Reference reports → upload a report you
trust and tick **Benchmark** → 🎯 Performance check:
1. **Build answer key**, review the figures (riskiest first), then **Accept all safe** or
   fix rows.
2. **Run performance check** and note coverage, accuracy and grounding.
3. Change the skill (🧩 Skills), run again, and compare in **History**.

See [EVALUATION.md](EVALUATION.md).

## Writing good skill instructions

* **The description decides when the skill runs.** The router reads only the description,
  so say what it covers and when to use it, and how it differs from similar skills.
* **Define terms precisely.** Brokers define take-up, vacancy and availability differently.
  Say which definition you want, and to record the source with every figure.
* **Give a method:** the reports to read, example searches (`"Savills London office lease
  length Q3 2026"`), and what to compare against.
* **Say how to record each metric:** per submarket? per quarter? which unit?
* **Keep plausible ranges generous.** They only exist to catch mis-read numbers.

## Safety nets

* **Nothing is lost.** Every save keeps the previous version (🕘 Earlier versions → Restore),
  and deleted skills can be restored from *Deleted skills*.
* **No silent overwrites.** If a colleague saved after you opened a skill, your save is refused.
  Click **Reload**, then re-apply your change.
* **Checks before saving.** The UI refuses anything that would stop the agent from loading,
  such as an unknown metric, no tools, or a name clash.
* **Protected items.** The summary skill (`market-synthesis`), metrics used by the report
  charts, and Central London / UK / London can't be removed.

## Sharing changes with the team

Changes are saved to the files above **on the machine running the UI**, and apply at once to
everyone using that UI. To reach the rest of the team, and to survive a deleted Codespace,
they must be **committed to git**. The Skills tab shows a blue banner listing changes not
yet committed. Ask a developer to review and commit them:

```bash
git status skills catalog       # see what changed
git diff skills catalog         # review
git add skills catalog && git commit -m "Add average lease length metric"
```

## Costs

| Action | Cost |
|---|---|
| Editing, validating, saving, tracking, managing submarkets | Free |
| Check feasibility / Draft with Claude / Check with Claude | One call to the strongest model (roughly 5-20 US cents; it reads the whole catalogue and skill list) |
| Test now / Test run | One research run (a few cents to ~$0.50 in live mode) |
| A skill with "Research this topic in every market brief" ticked | Runs in every scheduled / full brief, so it adds its research cost each time. Untick it to keep a topic on demand (chat only) |
| Performance check | Answer key: one call (a few cents). Figure run: only the skills that collect the figures (designed for under $1; estimate shown first). Brief judgement: one call; readability and citation checks are free |
