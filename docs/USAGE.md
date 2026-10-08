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
| `cre-monitor ask "question"` | One question in a **new** conversation; prints a cited answer, the skills used and the conversation id |
| `cre-monitor ask "..." --thread ID` | Continues conversation `ID`, so follow-up questions have context |
| `cre-monitor chat [--thread ID]` | Interactive multi-turn chat in the terminal: new conversation, or resume `ID`. Type `exit` to quit |
| `cre-monitor ask "..." --ref ID [--ref ID2]` | Uses up to 3 **earlier conversations as background context**. Works with `chat` too, where it applies to the whole session. See [Referencing earlier conversations](#referencing-earlier-conversations) |
| `cre-monitor conversations [--limit 20]` | Lists saved conversations (id, title, questions, last active), most recent first. The same list appears in the UI sidebar |
| `cre-monitor ui [--port 8501] [--debug]` | Streamlit web app (see [§2](#2-web-ui-cre-monitor-ui)). `--debug` shows Streamlit's developer toolbar (Rerun, Clear cache) |
| `cre-monitor schedule install --day MON --time 07:00` | Windows: registers a weekly brief in Task Scheduler. Linux, macOS and Codespaces: prints a crontab line instead |
| `cre-monitor schedule show` / `schedule remove` | Shows or removes the Windows scheduled task |

### Common combinations

```bash
cre-monitor --offline --demo brief                    # free, deterministic, no keys needed
cre-monitor --live brief --skills macro-economy      # cheapest real end-to-end check
cre-monitor --live ask "How is Canary Wharf vacancy trending?"
```

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
| **⚙️ Settings & brief** | **Offline data** toggle (same as `--offline`). **Demo mode** toggle (same as `--demo`; locked on without `ANTHROPIC_API_KEY`). Current model and data source. **Run full brief now** (same as `cre-monitor brief`; the result appears in the Briefs tab) |

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
| **Briefs** | Browse past briefs (newest first), view them inline, and download the HTML or Markdown |
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

* **Reset history:** delete `data/`. The metrics history is re-seeded from fixtures on the
  next run. Note that this also deletes all saved conversations.
* **Clear old reports:** delete `reports/`.
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
