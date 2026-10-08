# Usage guide

Everything you can run, and what each part of the UI does. For setup see the
[README](../README.md); for how it works inside, see [ARCHITECTURE.md](ARCHITECTURE.md).

- [1. CLI](#1-cli-cre-monitor-command)
- [2. Web UI](#2-web-ui-cre-monitor-ui)
- [3. Tests and evaluations](#3-tests-and-evaluations)
- [4. LangGraph Studio](#4-langgraph-studio-optional-for-developers)
- [5. Python API](#5-python-api)
- [6. Settings](#6-settings-env-or-environment-variables)
- [7. Files, outputs and housekeeping](#7-files-outputs-and-housekeeping)
- [8. GitHub Codespaces notes](#8-github-codespaces-notes)

---

## 1. CLI: `cre-monitor <command>`

Activate the environment first: `conda activate london-cre`. `python -m cre_monitor.cli ...`
is equivalent to `cre-monitor ...`; the scheduler uses that form.

### Global flags (put them *before* the command)

| Flag | Effect |
|---|---|
| `--offline` / `--online` | Data tools read `fixtures/` instead of the internet |
| `--demo` / `--live` | Demo uses canned findings and makes no LLM calls. Live calls Claude and needs `ANTHROPIC_API_KEY` |

Example: `cre-monitor --offline --demo brief`.

### Commands

| Command | What it does |
|---|---|
| `cre-monitor skills` | Lists the loaded skills, their tools and whether each is in the brief. Invalid `SKILL.md` files are shown in red |
| `cre-monitor brief` | Full market brief, written to `reports/<date>/` (HTML, Markdown, JSON, PNG charts). Log goes to `data/logs/` |
| `cre-monitor brief --skills office-rents,macro-economy` | Runs only those skills (cheaper; good for testing) |
| `cre-monitor brief --open` | Opens the HTML report when done (local machine only) |
| `cre-monitor brief --no-style` | Ignores the learned house style for this brief (built-in layout and wording) |
| `cre-monitor style learn [--from DIR] [--heuristic]` | Learns a **house style** from example reports in `style/reports/` (see [House style](#house-style-imitating-example-reports)) |
| `cre-monitor style show` / `style clear` | Shows the learned style profile, or removes it (back to the built-in style) |
| `cre-monitor ask "question"` | One question in a **new** conversation; prints a cited answer, the skills used and the conversation id |
| `cre-monitor ask "..." --thread ID` | Continues conversation `ID`, so follow-up questions have context |
| `cre-monitor chat [--thread ID]` | Interactive multi-turn chat in the terminal: new conversation, or resume `ID`. Type `exit` to quit |
| `cre-monitor ask "..." --ref ID [--ref ID2]` | Uses up to 3 **earlier conversations as background context**. Works with `chat` too, where it applies to the whole session. See [Referencing earlier conversations](#referencing-earlier-conversations) |
| `cre-monitor conversations [--limit 20]` | Lists saved conversations (id, title, questions, last active), most recent first. The same list appears in the UI sidebar |
| `cre-monitor ui [--port 8501] [--debug]` | Streamlit web app (see [§2](#2-web-ui-cre-monitor-ui)). `--debug` shows Streamlit's developer toolbar (Rerun, Clear cache) |
| `cre-monitor export [--since YYYY-MM-DD] [--include-logs] [--out DIR]` | Exports briefs, the metrics history and conversations as one zip in `exports/` (see [§7](#exporting-data)) |
| `cre-monitor merge PATH [--dry-run] [--no-reports] [--no-backup] [--yes]` | Merges another installation's data (metrics, conversations, agent memory, briefs) into this one. Shows a preview first. See [Merging installations](#merging-installations) |
| `cre-monitor briefs list [--limit 20]` | Lists generated briefs (id, created, HTML path), newest first |
| `cre-monitor briefs delete ID [--with-metrics] [--yes]` | Deletes a brief's files; asks for confirmation unless `--yes` is given. `--with-metrics` also removes its figures from the metrics history |
| `cre-monitor schedule install --day MON --time 07:00` | Windows: registers a weekly brief in Task Scheduler. Linux, macOS and Codespaces: prints a crontab line instead |
| `cre-monitor schedule show` / `schedule remove` | Shows or removes the Windows scheduled task |

### Common combinations

```bash
cre-monitor --offline --demo brief                    # free, deterministic, no keys needed
cre-monitor --live brief --skills macro-economy      # cheapest real end-to-end check
cre-monitor --live ask "How is Canary Wharf vacancy trending?"
```

### House style: imitating example reports

The brief can imitate the writing of a set of reports you admire (an in-house monthly, an
agency quarterly): voice and tone, section order and headings, headline and paragraph
style, number conventions ("£190 psf", "bp", "Q2 2026") and signature techniques
("compare with the long-term average").

Each step can be done in the terminal (below) or in the web UI's **🎨 House style** sidebar
panel (upload → **Learn style from these reports** → **Show learned profile**), with the
**Use house style** toggle next to **Run full brief now**. The profile is shared by everyone
using the same installation, whichever way it was learned.

1. Put up to 8 example reports in **`style/reports/`** (`.md`, `.txt`, `.html` or `.pdf`;
   the first ~6,000 characters of each are read). The folder is git-ignored except for its
   README, because examples are often licensed documents. **Check the licence first**:
   some publishers prohibit using their reports with AI tools.
2. Run `cre-monitor --live style learn`. Claude (synthesis model) analyses the examples
   and writes a **style profile**: `style/profile.json`, plus `style/profile.md` for humans
   to review. Without a key, or with `--heuristic`, a rule-based learner is used instead
   (headings, sentence length, bullets, voice, number conventions; no LLM, free).
3. Review `style/profile.md` (or `cre-monitor style show`). Commit `profile.json` if the
   team should share the style. Edit the JSON by hand if needed.
4. Run `cre-monitor brief`. The report header shows "House style".

What changes in a brief:

| Part | How the style is applied |
|---|---|
| **Layout** | Sections follow the profile's order and headings. Sections the profile doesn't mention keep their default headings and are placed before the reference sections (sources, data quality), so no content is ever dropped |
| **Executive summary, takeaways, risks** | The synthesis prompt carries the style profile (live mode) |
| **Topic headlines and summaries** | A style editor (one skill-model call per brief, live mode) rewrites them in the house style |

**Facts never change.** Figures come only from the agent's research. The style editor's
output is checked by a number guard: if a restyled topic adds or changes any number, the
original wording is kept for that topic. If the editor fails, the brief uses the original
text. Failed topics and the metrics themselves are never touched. The profile describes the
style; the agent is told never to copy sentences from the examples.

Switch it off for one brief with `brief --no-style` (or the UI toggle), permanently with `REPORT_STYLE=0`, or
remove it with `cre-monitor style clear`. In demo mode only the layout is applied (no LLM
rewriting). Chat answers are not affected.

---

## 2. Web UI: `cre-monitor ui`

Opens on port 8501: `http://localhost:8501` locally, or as a forwarded port in Codespaces.

Streamlit's **Deploy** button and developer options (rerun, clear cache) are hidden by
`toolbarMode = "viewer"`. It is set in `.streamlit/config.toml` and also passed by
`cre-monitor ui`. Deploy would publish to Streamlit Community Cloud, which this PoC is not
set up for: its storage is temporary and apps are public by default. The **⋮** menu
(theme, print) remains.

**Debug mode** brings back Streamlit's full developer toolbar: **Rerun** (also the `R`
key), **Clear cache**, and Deploy. The sidebar then shows "🐞 Debug mode".
* `cre-monitor ui --debug`, for one session;
* `CRE_UI_DEBUG=1` in `.env` or Codespaces secrets, to keep it on;
* `STREAMLIT_CLIENT_TOOLBAR_MODE=developer` when launching with plain `streamlit run`.

### Sidebar

The sidebar works like a modern chatbot.

| Control | Purpose |
|---|---|
| **➕ New chat** | Starts a fresh conversation. It appears in the list after its first question, titled by that question |
| **Conversation list** | Every saved conversation, newest first, grouped **Today / Yesterday / Previous 7 days / Older**. The open one is highlighted. Hover to see the question count and when it was last active |
| Click a conversation | Reopens it: questions, answers, skills used, charts and data-quality notes are redrawn. **Ask again to resume it**: the agent continues with the earlier messages as context, so follow-ups like "and the City?" work |
| **⌄** menu on a row | **Rename** the conversation, or **Delete** it. Delete removes both the list entry and the agent's memory of that thread |
| Page URL `?thread=<id>` | The open conversation is kept in the URL, so a refresh, bookmark or shared link reopens it. Ids are also listed by `cre-monitor conversations` |
| **📦 Export data** | Optional "since" date and "include logs". **Prepare export** builds the zip, then **⬇ Download** saves it (same as `cre-monitor export`) |
| **⚙️ Settings & brief** | **Offline data** toggle (same as `--offline`). **Demo mode** toggle (same as `--demo`; locked on without `ANTHROPIC_API_KEY`). Current model and data source. **Use house style** toggle (on when a style is learned; off = same as `--no-style`, for that brief only). **Skills in the brief** tick boxes (all ticked by default; **All** / **None** shortcuts; hover a skill for its description). **Run full brief now** (same as `cre-monitor brief`); with only some skills ticked it becomes **Run partial brief (n of 8 skills)** (same as `brief --skills …`: cheaper and quicker in live mode). Ticks are per browser session. The result appears in the Briefs tab |
| **🎨 House style** | Upload example reports, remove them (🗑), **Learn style from these reports** (tick **Quick analysis** for the free rule-based learner), **Show learned profile**, **Clear house style**. Same as `cre-monitor style learn / show / clear`; see [House style](#house-style-imitating-example-reports) |

Conversations started in the terminal (`cre-monitor ask` / `chat`) appear in the same list.
Research findings are never reused between turns: every question triggers fresh research,
and only the conversation text carries over.

### Referencing earlier conversations

Above the chat box, **📎 Reference earlier conversations** lets you pick up to 3 past chats
as background for your next question. Example: "How has that changed?" with last week's
Canary Wharf conversation selected.

* **What is shared.** A compact, dated summary of each referenced chat: its title and
  date, its recent questions, a short excerpt of each answer, and the key figures it
  reported (with period, source and date).
* **Who sees it.** Only the step that chooses skills and the step that writes the
  answer. The research skills never see it, so **figures always come from fresh
  research**.
* **How the answer uses it.** Current research takes precedence. The answer says when
  it draws on an earlier chat and gives its date, and it describes changes rather than
  repeating outdated figures.
* **How the selection behaves.** It is remembered per conversation until you change it.
  Each answer shows **📎 Referenced: …**, which is also redrawn when you reopen a
  conversation. Deleted conversations drop out of the selection automatically.
* **In the terminal:** `--ref ID`, repeatable.

In demo mode no LLM reasons over the references. The answer simply lists which
conversations would be used.

### Tabs

| Tab | Purpose |
|---|---|
| **Chat** | Multi-turn Q&A. Shows live progress (which skills are running), then the answer with its sources, the skills used, any relevant charts and the data-quality notes |
| **Briefs** | Browse past briefs (newest first), view them inline, and download the HTML or Markdown. **🗑 Delete brief** opens a confirmation that removes the brief's HTML, Markdown, findings JSON and charts. The **Also remove its figures from the metrics history** checkbox (off by default) also deletes that run's figures, which changes "what changed" deltas and Dashboard trends |
| **Dashboard** | Explore the metric history in `data/metrics.sqlite`. Pick a metric (e.g. prime rent, vacancy rate, Bank Rate, CPIH) and up to 4 submarkets to see a trend chart and its data table. Each line follows one source; dashed lines mix sources and are not like-for-like. History starts from the seeded fixtures and grows with every brief and chat. It is read-only: no research and no cost |

### When something goes wrong

If part of the work fails (most often the Claude API: invalid key, access denied, no
credit, rate limit, outage, network), users never see raw error text. Instead they get:

* **A red panel** ("We couldn't answer this question") when nothing usable was produced,
  or **an amber panel** ("this answer may be incomplete") when only some steps failed.
  Each panel gives a plain-English title, an explanation and **What you can do**.
* **A reference ID**, e.g. `ERR-20261008-1217-F1E4`, with a copy button. The panel also
  shows who to send it to (`SUPPORT_CONTACT`).
* **Technical details (for engineers)**, collapsed: the category, the affected steps,
  the conversation and run IDs, the log file, and the raw messages.

The panel is saved with the turn, so it reappears when the conversation is reopened. The
same information is printed in the terminal by `ask`, `chat` and `brief`.
**Run full brief now** shows a compact version in the sidebar.

**In briefs (HTML and Markdown)** the same treatment applies, and the reference ID matches
the one shown in the terminal or UI:
* a red or amber **problem panel** under the title, with the plain-English problem, what to
  do, the reference and the support contact;
* each failed topic section reads "⚠ Not available this time: \<problem\>. Reference ERR-…";
* raw "Skill failed" lines are left out of the data-quality notes;
* raw error text appears only in **Technical details for engineers**: collapsed at the end
  of the HTML, and an appendix in the Markdown;
* the findings JSON keeps the full audit trail, including the incident.

**For engineers tracing a reference:**

```bash
grep -A5 ERR-20261008-1217-F1E4 data/logs/*.log      # PowerShell: Select-String -Path data\logs\*.log -Pattern ERR-... -Context 0,5
```

One `ERROR` record holds the category, scope, thread, run, mode, and each failed step's
exact error. Logs: `ui_<date>.log` (web UI), `chat_<date>.log`, `brief_<date>.log` (CLI).

| Category | Typical cause | Shown to users as |
|---|---|---|
| `access_denied` | HTTP 403: account lacks access, or the API is unavailable from the location | "The AI service refused the request" |
| `auth` | HTTP 401: missing, invalid or revoked API key | "The AI service key was not accepted" |
| `credit` | Credit balance exhausted | "AI usage credit has run out" |
| `rate_limit` | HTTP 429 | "The AI service is busy" (retry) |
| `service` | HTTP 5xx / 529 overloaded | "Temporarily unavailable" (retry) |
| `app_error` | HTTP 400 `invalid_request_error`: the app sent a request the API rejected (an app bug) | "The app sent a request the AI service rejected" |
| `network` | Connection, DNS, TLS or timeout errors | "Could not reach the AI service" |
| `config` | Live mode without a key configured | "Not configured for live AI research" |
| `unknown` | Anything else | "Something went wrong" |

### Sharing the UI

Forwarded ports in Codespaces are private by default. To share, open the **Ports** panel,
right-click 8501, choose **Port Visibility**, then **Organization** or **Public**. Things to know:
* the link only works while the codespace runs;
* there is no app login;
* all usage is billed to your API keys;
* Anthropic's regional rules apply to whoever uses it.

---

## 3. Tests and evaluations

How the tests work and how to add them: [TESTING.md](TESTING.md).

| Command | What it checks | Cost |
|---|---|---|
| `pytest` | Offline suite: skills, tools, validator, store, charts, the full graph (demo and fake LLM) and the Streamlit UI | Free, ~10 s |
| `pytest tests/test_graph.py -v` | One file only (end-to-end pipeline) | Free |
| `pytest -m live` | Real BoE, ONS, Nomis, Google News and Tavily calls, plus one real skill run if a key is set | Tavily credits, a few cents |
| `pytest -m live -k "not skill"` | Live data sources only, without Claude | Tavily only |
| `python evals/run_evals.py` | 7 chat questions: correct routing, grounded and cited answers (demo mode) | Free |
| `python evals/run_evals.py --live` | Same, against the real agent and live data | A few USD |

---

## 4. LangGraph Studio (optional, for developers)

```bash
pip install -e ".[studio]"
langgraph dev        # opens a browser view of the graph: step through nodes, inspect state
```
Needs a `.env` file because `langgraph.json` references it.

---

## 5. Python API

```python
from cre_monitor.graph.builder import run_brief, ask
state = run_brief(["macro-economy"])               # state["report_paths"], ["findings"], ["synthesis"]
state = ask("Prime rents in the West End?", thread_id="t1")   # state["answer"]

from cre_monitor.graph.nodes.skill_runner import run_skill
finding = run_skill("office-rents", "Latest prime rents?")    # one skill -> SkillFinding

from cre_monitor.store import get_store
get_store().series("prime_rent", "West End")       # metric history (DataFrame)

from cre_monitor.tools import TOOLS
print(TOOLS["boe_series"].invoke({"name": "gilt_10y_yield"}))  # call any data tool directly
```

---

## 6. Settings (`.env` or environment variables)

The full template is in `.env.example`.

| Setting | Purpose |
|---|---|
| `ANTHROPIC_API_KEY`, `TAVILY_API_KEY` | API keys. Demo mode turns on automatically without the Anthropic key |
| `MODEL_ROUTER` / `MODEL_SKILL` / `MODEL_SYNTHESIS` | Model for each stage |
| `EFFORT_SKILL` / `EFFORT_SYNTHESIS` | `low` to `max`: the main cost/quality dial |
| `SKILL_MAX_STEPS` | Research turns per skill (default 12) |
| `CRE_OFFLINE`, `CRE_DEMO_MODE` | Default run modes |
| `REPORT_PNG=0` | Skip PNG charts (needed if no Chrome/Chromium is installed) |
| `REPORT_STYLE=0` | Ignore the learned house style (`style/profile.json`) in briefs |
| `STYLE_DIR` | Where the style profile and `reports/` examples live (default `style/`) |
| `STALE_AFTER_DAYS` | When the validator flags data as stale |
| `SUPPORT_CONTACT` | Who users should send error reference IDs to (shown in error panels) |
| `CRE_UI_DEBUG=1` | UI debug mode: Streamlit developer toolbar (Rerun, Clear cache) |

---

## 7. Files, outputs and housekeeping

| Path | Contents |
|---|---|
| `reports/<date>/` | `brief_<run>.html`, `brief_<run>.md`, `charts/<run>/*.png`, `findings_<run>.json` |
| `data/metrics.sqlite` | Metric history used by deltas, charts and the Dashboard |
| `data/checkpoints.sqlite` | Agent chat memory per thread (LangGraph) |
| `data/conversations.sqlite` | Conversation list: titles and per-turn details for the sidebar |
| `data/logs/` | `brief_<date>.log`, `chat_<date>.log` (CLI), `ui_<date>.log` (web UI). Error references (`ERR-…`) are logged here |
| `exports/` | Export zips from `cre-monitor export` / the sidebar (git-ignored) |
| `data/backups/pre-merge_<timestamp>/` | Automatic database backups taken before each `cre-monitor merge` |
| `merge-in/<name>/` | Data from other installations waiting to be merged (git-ignored, except its README) |
| `style/reports/` | Example reports for the house style (git-ignored, except its README) |
| `style/profile.json` / `profile.md` | The learned house style (committable) and its readable summary |

* **Reset history:** delete `data/`. The metrics history is re-seeded from fixtures on the
  next run. Note that this also deletes all saved conversations.
### Exporting data

`cre-monitor export`, or **📦 Export data** in the sidebar, writes
`exports/cre-export_<YYYYMMDD-HHMMSS>.zip`:

| File | For | Contents |
|---|---|---|
| `cre-export.xlsx` | Business users / Excel / Power BI | Sheets **Metrics** (every figure with source), **Briefs** (index), **Conversations** (one row per question/answer, with error references) |
| `metrics.csv` | Analysis | Full metric history: key, submarket, period, value, unit, source, URL, publication date, notes, run |
| `briefs/<date>/` + `briefs_index.csv` | Sharing | Each brief's HTML (opens in a browser), Markdown, findings JSON and charts |
| `conversations/*.md` | Reading | One transcript per conversation, with skills used, references and error references |
| `conversations.json` | Engineers / re-use | The same in structured form, including findings and incidents |
| `manifest.json`, `README.md` | Recipients | Export time, version, filters and counts, plus a guide to the files |
| `logs/` | Engineers | Only with `--include-logs` |

* `--since` filters metrics by run date, briefs by creation date and conversations by last
  activity. The seeded starter history is only included in full exports.
* Agent memory (LangGraph checkpoints) is not exported; it is an internal format.
  API keys are never part of the data.
* **Full backup or a move to another machine:** copy `data/` and `reports/` while the app
  is stopped. The export is for people and analysis; the folders are the complete backup.
* Figures come from third-party sources. Exports are for internal use; check licensing
  before sharing them externally.

### Merging installations

Use this to combine data from another copy of the app, for example a colleague's machine
or a Codespace, into this one:

```bash
cre-monitor merge /path/to/other/london-cre-monitor      # or .../data; shows a preview, then asks
cre-monitor merge /path/to/other --dry-run              # preview only
```

1. **Stop both apps first**, so no database is mid-write.
2. Copy the other installation's `data/` folder (and `reports/` if you want its briefs) into
   **`merge-in/<name>/`** in this repo. That folder is git-ignored, so the data is never
   committed. In Codespaces, download the folders from the file explorer.
3. Run `cre-monitor merge merge-in/<name>` and review the preview table.

| Data | What happens |
|---|---|
| Metrics | Rows not already present are added. The other copy's starter (seed) history is skipped if this one has its own |
| Conversations | **Added** if new. **Already present** ones are skipped. **Extended** if the conversation continued on the other machine (only the new questions are added). **Renamed** (`<id>-xxxx`) if the same id holds a different history; references to it are updated |
| Agent memory | Copied with its conversations, so merged chats can be resumed |
| Briefs | Missing files are copied. If the same file exists with different content, this installation's copy is kept and listed as a conflict |

* **Safe to re-run:** existing data is never overwritten, and already-merged data is skipped.
* **All or nothing:** the merge either completes fully or leaves your data exactly as it
  was.
  * It first rehearses on in-memory copies, so data problems stop it before anything is
    written.
  * It then locks the databases. If something is writing to them (e.g. the app finishing
    a chat), it stops with "in use … Nothing was changed".
  * If anything fails after writing has begun (disk full, interruption, …), all databases
    are restored automatically from the backup, and brief files copied by that run are
    removed. The message says "restored to its pre-merge state" and gives an `ERR-`
    reference.
* **Backup first:** the current databases are copied to `data/backups/pre-merge_<timestamp>/`
  before anything changes. To undo a *successful* merge, stop the app and copy those files
  back into `data/`. `--no-backup` also disables the automatic restore, so avoid it.
* An app that is open but idle can't be detected. Stop it anyway: while a merge runs, the
  app can't save, and it won't show merged conversations until it is restarted.
* The other installation is only read, never modified.
* This merges SQLite data between installations of this app. It does not import the
  export zip.

* **Delete one brief:** Briefs tab → 🗑 Delete brief, or `cre-monitor briefs delete <id>`.
  Same-day briefs are unaffected, and an empty date folder is removed.
* **Clear all old reports:** delete `reports/`.
* Both folders are git-ignored. What is stored, when, and the table schema are covered in
  [DATA_MODEL.md §6](DATA_MODEL.md#6-persistence-what-is-stored-where).

---

## 8. GitHub Codespaces notes

* Setup is automatic (`.devcontainer/`). If the env is missing, run `bash .devcontainer/post-create.sh`
  or `conda env create -f environment.yml && conda activate london-cre`.
* Everything above works except `brief --open` (there is no desktop browser) and `schedule install`
  (there is no Task Scheduler, and a codespace stops when idle).
* First check: `pytest`, then `cre-monitor --offline --demo brief`, then a single live skill.
* Anthropic's API is only available in supported regions, and that applies to the people
  using it, not just where the code runs.
