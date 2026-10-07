# London CRE Market Monitor

A **LangGraph agent PoC** that monitors the London office market for Nan Fung Group's
London team. It replaces manual desk research with a recurring, **cited, chart-backed
market brief** and a **chat assistant** you can question on demand.

It covers:

| Area | Skill |
|---|---|
| Prime & Grade A rents, incentives | `office-rents` |
| Vacancy & availability | `vacancy-availability` |
| Leasing take-up & major deals | `leasing-take-up` |
| Development pipeline, refurbishments, pre-lets | `supply-pipeline` |
| City / West End / Midtown / King's Cross / Canary Wharf / ... | `submarket-dynamics` |
| Rates, gilts, inflation, GDP, employment (BoE / ONS) | `macro-economy` |
| Flight-to-quality, ESG/MEES, hybrid working | `occupier-demand` |
| Emerging news & events, investment | `news-events` |
| Executive synthesis (meta-skill) | `market-synthesis` |

The agent is **architected around skills**. Each skill is a folder with a `SKILL.md`
file. To add a research area, you add a folder; the graph code doesn't change.
See [docs/SKILLS.md](docs/SKILLS.md).

---

## Quick start

```powershell
# 1. Create the conda environment (Python 3.12) and install the package
conda env create -f environment.yml
conda activate london-cre
# (equivalent manual route: conda create -n london-cre python=3.12; pip install -e ".[dev]")

# 2. Configure keys (optional - without them the app runs in demo mode)
copy .env.example .env      # then edit .env

# 3. Try it
cre-monitor skills                     # list the loaded skills
cre-monitor --offline brief --open     # full brief from fixture data, opens the HTML report
cre-monitor ask "How is Canary Wharf vacancy trending?"
cre-monitor ui                         # Streamlit chat + briefs + dashboard
```

### Run modes

Two independent switches. Set them in `.env` or as CLI flags.

| | LLM (`--live`) | No LLM (`--demo`) |
|---|---|---|
| **Live data** (`--online`) | Real agent: Claude researches the live web, BoE and ONS | Canned findings; macro tools still live |
| **Fixtures** (`--offline`) | Real agent reasoning over the fixture data | Fully deterministic. Used by the tests and for demos |

* **Demo mode** turns on automatically when `ANTHROPIC_API_KEY` is missing, so a fresh
  checkout always runs.
* `TAVILY_API_KEY` is optional. Without it, web search falls back to Google News RSS,
  which covers news articles only (no broker PDFs).

---

## What you get

### 1. Text + chart market brief
`cre-monitor brief` writes the following to `reports/<date>/`:
* `brief_<run>.html`: self-contained interactive report containing:
  * KPI tiles with the change versus the previous period
  * executive summary
  * what changed since the last period
  * risk/opportunity matrix
  * charts: prime rents, vacancy, take-up vs the 10-year average, pipeline, rates
  * one section per skill, with data tables
  * watch list, data-quality notes and sources
* `brief_<run>.md`: the same content as Markdown, with PNG charts, for email or a wiki.
* `findings_<run>.json`: raw structured output, kept as an audit trail.

### 2. Scheduled run
```powershell
cre-monitor schedule install --day MON --time 07:00   # Windows Task Scheduler
cre-monitor schedule show
cre-monitor schedule remove
```
On Linux/macOS, `schedule install` prints the crontab line instead. Scheduled runs log to
`data/logs/`.

### 3. Chat UI
`cre-monitor ui` opens Streamlit with three tabs:
* **Chat**: multi-turn Q&A. You can watch progress as it happens (which skills ran),
  and answers come with charts and data-quality notes.
* **Briefs**: browse and download past briefs.
* **Dashboard**: time series of any metric by submarket, from the metrics history.

There is also a terminal chat: `cre-monitor chat`.

### 4. LangGraph Studio (optional)
```powershell
pip install -e ".[studio]"
langgraph dev        # uses langgraph.json; needs a .env file
```

---

## How it works

```
             ┌──────────── brief: all skills / chat: router LLM picks 1-3 skills
             │
START ─► planner ─Send─► skill_runner × N  (parallel; each is a ReAct sub-agent
                         │                   with only its own tools + SKILL.md)
                         ▼
                     validator   ← deterministic checks: ranges, units, staleness,
                         │         missing citations, cross-source conflicts
                         ▼
                      persist    ← SQLite metric history → period-on-period deltas
                     ┌───┴────┐
              brief  ▼        ▼  chat
               synthesis   chat_answer ─► END
                   ▼
             report_writer ─► END   (HTML + Markdown + charts)
```

Full details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

### Data sources
| Tool | Source | Key needed |
|---|---|---|
| `web_search` | Tavily (domain-filtered to brokers & trade press) → fallback Google News RSS | Tavily optional |
| `fetch_document` | Any HTML page or PDF (broker research) | no |
| `rss_news` | Google News search, Estates Gazette, Bank of England, ONS release calendar | no |
| `boe_series` | Bank of England IADB: Bank Rate, SONIA, 10y gilt | no |
| `ons_series` | ONS time series (CPIH, CPI, unemployment, GDP) + Nomis (London employment) | no |
| `metrics_history` | The agent's own SQLite history | no |

All six tools fall back to `fixtures/` in offline mode.

---

## Repository layout

```
skills/<name>/SKILL.md      Skill definitions (frontmatter + expert instructions)
src/cre_monitor/
  config.py                 Settings (.env); run modes
  schemas.py                Pydantic contracts: SkillFinding, Metric, Signal, ...
  llm.py                    Model factory (router / skill / synthesis tiers)
  skills/registry.py        Discovers + validates skills (progressive disclosure)
  tools/                    LangChain tools + offline fixture fallbacks
  graph/state.py            LangGraph state + reducers
  graph/nodes/*.py          One module per graph node
  graph/builder.py          Graph wiring; run_brief() / ask()
  store/metrics.py          SQLite metric history + deltas
  reporting/                Plotly charts, Jinja2 templates, renderer
  cli.py                    `cre-monitor` CLI incl. scheduler
  ui/app.py                 Streamlit app
fixtures/                   Offline data (cited real figures) for tests & demos
tests/                      pytest suite (offline by default; `-m live` for real APIs)
evals/                      Chat evaluation questions + runner
docs/                       Architecture, skill authoring guide
```

## Testing

```powershell
pytest                       # offline, no keys, ~10s
pytest -m live               # live public APIs (and a real skill run if ANTHROPIC_API_KEY is set)
python evals/run_evals.py    # chat eval set (routing + grounded, cited answers); add --live for the real agent
```

`pytest` covers skills, tools, validator, store, charts, the full graph (demo and fake-LLM),
and the Streamlit UI (via Streamlit's headless `AppTest`).

The fake-LLM tests (`tests/fake_llm.py`) drive the **real** ReAct skill sub-agent with
scripted tool calls. That proves the tool loop, structured output, routing and synthesis
wiring work without spending tokens.

PNG chart export (for the Markdown report) uses kaleido, which needs a local Chrome or
Chromium. If none is installed, run `plotly_get_chrome`, or set `REPORT_PNG=0`. The HTML
report doesn't need it.

## Limitations & next steps
* Broker research is often PDF-only and published with a lag. Coverage is best with
  Tavily enabled. Paid data (CoStar, PMA, EGi) could be added later as new tools.
* Brokers define vacancy and take-up differently. The system handles this in three ways:
  * the validator flags disagreements rather than resolving them;
  * "what changed" prefers same-source comparisons and labels cross-source ones;
  * charts use a consistent source, and draw mixed-source lines dashed.
* The demo fixtures hold real Q1/Q2 2026 figures, but only a few historical points.
  Trend charts get richer as scheduled runs accumulate history.
* SQLite and a local scheduler suit a PoC. For production: Postgres, a hosted
  scheduler, LangSmith tracing, and report delivery by email or Teams.

Contributing guidelines: [CONTRIBUTING.md](CONTRIBUTING.md).
