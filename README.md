# London CRE Market Monitor

A **LangGraph agent PoC** that monitors the London office market for a London real estate
investment team. It replaces manual desk research with a recurring, **cited, chart-backed market brief**,
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

**See a real output:** [open the sample brief](examples/sample-brief/brief_20261008T070945-5e5fe0.md)
(with charts) - a full live run (all 8 skills, Q2 2026 data), with licence-restricted sources
removed. What was removed and why: [examples/sample-brief/](examples/sample-brief/README.md).

## License

This repository is provided under the [Proprietary Evaluation License](LICENSE). Permission is
limited to viewing, executing, and evaluating the code. Commercial, internal, or production use;
modifications outside technical evaluation; and redistribution are prohibited. See [LICENSE](LICENSE)
for the full terms.

## Quick start

```powershell
conda env create -f environment.yml      # creates the 'london-cre' env (Python 3.12) + installs the package
conda activate london-cre
copy .env.example .env                    # add ANTHROPIC_API_KEY (+ optional TAVILY_API_KEY)

cre-monitor --offline --demo brief --open # free demo brief from fixture data
cre-monitor ask "How is Canary Wharf vacancy trending?"
cre-monitor ui                            # web UI: Chat / Briefs / Dashboard
pytest                                    # offline test suite (~1 min); pytest tests/unit for ~4 s
```

Without an Anthropic key the app runs in **demo mode**: canned findings, no LLM calls.

**GitHub Codespaces:** create a codespace from the repo. `.devcontainer/` builds the same
conda env automatically. Add the keys as Codespaces secrets.

> **⚠️ Set the codespace region before you create it (needed for the Claude API).** A codespace
> runs in one of GitHub's regions (US East, US West, Europe West, Southeast Asia, Australia),
> picked automatically from your location unless you choose one. The Claude API only accepts
> requests from [supported countries](https://www.anthropic.com/supported-countries), so pick a
> region in a supported country:
> * for all your codespaces: **GitHub → Settings → Codespaces → Region → Set manually**;
> * for one codespace: **Code → Codespaces → ⋯ → New with options… → Region**.
>
> A codespace's region can't be changed later; create a new one if needed. In the wrong region,
> live runs fail with "The AI service refused the request" (HTTP 403). The region only decides
> where the VM runs: Anthropic's terms still require the people using the app to be in a
> supported country.

**All commands, UI features, settings and the Python API: [docs/USAGE.md](docs/USAGE.md).**

## What you get

| Output | How |
|---|---|
| Market brief: executive summary, KPIs, what changed, risk/opportunity matrix, charts, per-topic sections, sources | `cre-monitor brief` writes HTML, Markdown and JSON to `reports/<date>/` |
| House style: briefs imitate the voice, layout, number conventions and techniques of example reports you supply (facts are never changed) | Add examples to `style/reports/`, then `cre-monitor style learn` ([how](docs/USAGE.md#house-style-imitating-example-reports)) |
| Dashboard of tracked metrics: headline cards, comparison across all submarkets, trends on a real time axis | `cre-monitor ui` → 📈 Dashboard |
| No-code contributions: edit/add/delete research skills (Claude can draft them), add metrics (Claude checks they can be collected), manage submarkets | `cre-monitor ui` → 🧩 Skills, Dashboard → ⚙️ Metrics / 📍 Submarkets ([guide](docs/CONTRIBUTING_UI.md)) |
| Performance check: is the research right? Scores the live agent's figures (coverage, accuracy, made-up numbers, citations) and briefs (themes, readability) against reference reports you supply | `cre-monitor ui` → 📚 Reference reports → 🎯 Performance check, or `cre-monitor bench` ([how](docs/EVALUATION.md)) |
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
| [examples/sample-brief/](examples/sample-brief/README.md) | A real brief from a full live run (redacted), and how to publish another |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Design goals, graph and nodes, skills mechanism, house style, extension points |
| [style/reports/README.md](style/reports/README.md) | Supplying example reports for the house style (and the licence caveat) |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | Every data structure (models, graph state, skill metadata), persistence and SQLite schema, fixture formats |
| [docs/EVALUATION.md](docs/EVALUATION.md) | The performance check: answer keys, metrics, cost, reading the scorecard, limits |
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
* **No UI login.** Anyone with the link can use the app and edit skills, metrics and
  submarkets (version history makes every edit undoable). Put it behind SSO before sharing
  beyond the team.
* **PoC infrastructure:** SQLite and a local scheduler. Production would need hosted
  infrastructure and tracing. What is already hardened (network guard, HTML escaping,
  concurrency, CI) is listed in [ARCHITECTURE.md](docs/ARCHITECTURE.md#security-and-robustness-in-place).
* **Live path partly verified:** see [TESTING.md → Known gaps](docs/TESTING.md#8-known-gaps).
