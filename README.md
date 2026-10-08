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
| Scheduled weekly brief | `cre-monitor schedule install` (Windows Task Scheduler; prints a crontab line elsewhere) |
| Chat assistant | `cre-monitor ui` (Streamlit) or `cre-monitor chat` (terminal) |

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
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Design, graph and nodes, persistence, testability, extension points |
| [docs/SKILLS.md](docs/SKILLS.md) | Writing and adding skills; refreshing fixtures |
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
