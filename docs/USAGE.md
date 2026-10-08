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
| `cre-monitor ask "question"` | One question; prints a cited answer and the skills used |
| `cre-monitor ask "..." --thread NAME` | Same, but on a named thread so follow-up questions have context |
| `cre-monitor chat [--thread NAME]` | Interactive multi-turn chat in the terminal. Type `exit` to quit |
| `cre-monitor ui [--port 8501]` | Streamlit web app (see [§2](#2-web-ui-cre-monitor-ui)) |
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

### Sidebar

| Control | Purpose |
|---|---|
| **Offline data** toggle | Same as `--offline`: tools use fixtures |
| **Demo mode** toggle | Same as `--demo`. Locked on when no `ANTHROPIC_API_KEY` is set |
| **New conversation** | Starts a fresh chat **thread**, with a new thread ID and an empty chat. The agent remembers the conversation per thread, so follow-ups like "and the City?" have context; starting a new thread drops that memory. Use it when you change topic. Old threads stay saved in `data/checkpoints.sqlite`, but the UI cannot reopen them. Research findings are never carried over between turns; every question triggers fresh research |
| **Run full brief now** | Runs the same brief as `cre-monitor brief`. The result appears in the Briefs tab |

### Tabs

| Tab | Purpose |
|---|---|
| **Chat** | Multi-turn Q&A. Shows live progress (which skills are running), then the answer with its sources, the skills used, any relevant charts and the data-quality notes |
| **Briefs** | Browse past briefs (newest first), view them inline, and download the HTML or Markdown |
| **Dashboard** | Explore the metric history in `data/metrics.sqlite`. Pick a metric (e.g. prime rent, vacancy rate, Bank Rate, CPIH) and up to 4 submarkets to see a trend chart and its data table. Each line follows one source; dashed lines mix sources and are not like-for-like. History starts from the seeded fixtures and grows with every brief and chat. It is read-only: no research and no cost |

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

---

## 7. Files, outputs and housekeeping

| Path | Contents |
|---|---|
| `reports/<date>/` | `brief_<run>.html`, `brief_<run>.md`, `charts/<run>/*.png`, `findings_<run>.json` |
| `data/metrics.sqlite` | Metric history used by deltas, charts and the Dashboard |
| `data/checkpoints.sqlite` | Chat memory per thread |
| `data/logs/` | `brief_<date>.log`, `chat_<date>.log` |

* **Reset history:** delete `data/`. It is re-seeded from fixtures on the next run.
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
