# London CRE Market Monitor

A **LangGraph agent PoC** that monitors the London office market for Nan Fung Group's London
team. It replaces manual desk research with a recurring, **cited, chart-backed market brief**,
a **scheduled run** and a **chat assistant**.

It covers:
* prime and Grade A rents;
* vacancy;
* leasing take-up;
* the supply pipeline;
* submarket dynamics;
* macro conditions (Bank of England, ONS);
* occupier demand (flight to quality, ESG, hybrid working);
* news.

The agent is **built from skills**. Each research area is a folder with a `SKILL.md` file
(`skills/`), so adding a topic means adding a folder.

## Quick start

```powershell
conda env create -f environment.yml      # creates the 'london-cre' env (Python 3.12) + installs the package
conda activate london-cre
copy .env.example .env                    # add ANTHROPIC_API_KEY (+ optional TAVILY_API_KEY)

cre-monitor --offline --demo brief --open # free demo brief from fixture data
cre-monitor ask "How is Canary Wharf vacancy trending?"
cre-monitor ui                            # web UI: Chat / Briefs / Dashboard
pytest                                    # offline test suite (~10 s)
```

Without an Anthropic key the app runs in **demo mode**: canned findings, no LLM calls.

**GitHub Codespaces:** create a codespace from the repo. `.devcontainer/` builds the same
conda env automatically. Add the keys as Codespaces secrets.

**All commands, UI features, settings and the Python API: [docs/USAGE.md](docs/USAGE.md).**

## What you get

| Output | How |
|---|---|
| Market brief: executive summary, KPIs, what changed, risk/opportunity matrix, charts, per-topic sections, sources | `cre-monitor brief` writes HTML, Markdown and JSON to `reports/<date>/` |
| House style: briefs imitate the voice, layout, number conventions and techniques of example reports you supply (facts are never changed) | Add examples to `style/reports/`, then `cre-monitor style learn` ([how](docs/USAGE.md#house-style-imitating-example-reports)) |
| Dashboard of tracked metrics: headline cards, comparison across all submarkets, trends on a real time axis | `cre-monitor ui` → 📈 Dashboard |
| No-code contributions: edit/add/delete research skills (Claude can draft them), add metrics (Claude checks they can be collected), manage submarkets | `cre-monitor ui` → 🧩 Skills, Dashboard → ⚙️ Metrics / 📍 Submarkets ([guide](docs/CONTRIBUTING_UI.md)) |
| Scheduled weekly brief | `cre-monitor schedule install` (Windows Task Scheduler; prints a crontab line elsewhere) |
| Chat assistant with saved conversations: reopen and resume past chats from the sidebar, and reference earlier chats as background | `cre-monitor ui` (Streamlit) or `cre-monitor chat` (terminal) |
| Data export: briefs, metrics history and conversations as one zip (Excel, CSV, Markdown, JSON) | `cre-monitor export` or **📦 Export data** in the UI |
| Merge another installation's data (metrics, conversations, agent memory, briefs) into this one | `cre-monitor merge <path>` (preview, automatic backup, safe to re-run) |

## How it works

```
START ─► planner ─Send─► skill_runner × N ─► validator ─► persist ─┬─► synthesis ─► report_writer   (brief)
         (brief: all skills;   (parallel ReAct sub-agents,  (deterministic   (SQLite      └─► chat_answer                     (chat)
          chat: LLM picks)      each with its own tools)     checks)          history)
```

* **Data:**
  * Tavily or Google News search;
  * HTML/PDF reader;
  * RSS feeds;
  * Bank of England, ONS and Nomis APIs;
  * the agent's own metric history.

  Every tool has an offline fixture fallback.
* **Models:** Claude, in three tiers:
  * Haiku routes chat questions to skills;
  * Sonnet runs the research skills;
  * Opus writes the summary and chat answers.

## Documentation

| Doc | For |
|---|---|
| [docs/USAGE.md](docs/USAGE.md) | Every command, the UI guide, settings, Python API, outputs, Codespaces |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Design goals, graph and nodes, skills mechanism, house style, extension points |
| [style/reports/README.md](style/reports/README.md) | Supplying example reports for the house style (and the licence caveat) |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | Every data structure (models, graph state, skill metadata), persistence and SQLite schema, fixture formats |
| [docs/TESTING.md](docs/TESTING.md) | What "testable" means here, techniques, per-file test coverage, fake LLM, evals, adding tests |
| [docs/SKILLS.md](docs/SKILLS.md) | Writing and adding skills; refreshing fixtures |
| [docs/CONTRIBUTING_UI.md](docs/CONTRIBUTING_UI.md) | For non-developers: changing skills, metrics and submarkets in the web UI |
| [fixtures/README.md](fixtures/README.md) | Provenance of the offline demo data |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Team conventions |

## Limitations

* **Anthropic API availability:** the API is only offered in supported regions. This
  applies to the people using it, not only where the code runs.
* **Broker definitions differ.** The agent flags conflicts and labels cross-source
  comparisons instead of resolving them.
* **Coverage:** best with Tavily. Some broker data is licence-restricted and is
  deliberately not used.
* **PoC infrastructure:** SQLite, a local scheduler and no UI login. Production would need
  hosted infrastructure, tracing and authentication.
