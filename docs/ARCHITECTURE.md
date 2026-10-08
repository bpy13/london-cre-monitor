# Architecture

This document explains *why* the system is shaped the way it is. For setup, see the
[README](../README.md). For commands and the UI, see [USAGE.md](USAGE.md). For data
structures and storage, see [DATA_MODEL.md](DATA_MODEL.md). For tests, see
[TESTING.md](TESTING.md). For writing skills, see [SKILLS.md](SKILLS.md).

## Design goals

1. **Testable.** Every component runs offline and without API keys. The full graph is
   exercised by the test suite with fixtures and a scripted fake LLM
   ([TESTING.md](TESTING.md)).
2. **Extensible by domain experts.** Research areas are *skills* written mostly in
   Markdown. Adding one doesn't require changing graph code.
3. **Trustworthy output.** Every figure carries a source. Deterministic validation runs
   before anything is stored or reported. Conflicts between sources are disclosed, not hidden.
4. **Memory of the market.** Metrics are persisted across runs, so the agent reports
   *shifts* ("vacancy fell 60bp") and not just snapshots.
5. **Cost-aware.** A cheap model routes, a mid-tier model researches, and the top model
   synthesises. Per-skill step caps bound the spend.

## Components

```
            ┌────────────────────────── cre_monitor ───────────────────────────┐
 CLI ──┐    │                                                                  │
 UI  ──┼──► │ graph/builder.py ──► nodes ──► skills/registry ──► skills/*.md   │
 cron ─┘    │        │               │                                         │
            │        │               ├──► tools/ ──► web, PDFs, RSS, BoE, ONS  │
            │        │               │        └───► fixtures/ (offline)        │
            │        │               ├──► llm.py ──► Claude (3 tiers)          │
            │        │               └──► store/metrics.py ──► data/*.sqlite   │
            │        └──► reporting/ ──► reports/<date>/ (HTML, MD, PNG, JSON)  │
            └──────────────────────────────────────────────────────────────────┘
```

## The graph

| Node | Type | Responsibility |
|---|---|---|
| `planner` | logic (+ router LLM in chat) | Pick skills, reset per-run state, assign `run_id` |
| `fan_out` | conditional edge | Emit one `Send("skill_runner", SkillTask)` per skill → **parallel** execution |
| `skill_runner` | sub-agent | Run one skill as its own compiled LangGraph (see below) → `SkillFinding` |
| `validator` | deterministic | Range/unit/vocabulary/staleness/citation checks; flags cross-source conflicts; drops implausible metrics |
| `persist` | deterministic | Seed history on first run, compute deltas vs earlier periods, append metrics |
| `synthesis` | LLM (brief) | `market-synthesis` meta-skill → `ExecutiveSynthesis` |
| `report_writer` | deterministic | Charts + HTML/Markdown/JSON |
| `chat_answer` | LLM (chat) | Cited conversational answer, appended to `messages` |

### State and reducers (`graph/state.py`)
* `messages` uses `add_messages`. With the SQLite checkpointer, conversation history
  persists per `thread_id`, so follow-up questions work.
* `findings` uses a custom reducer (`merge_findings`):
  * parallel skill runners **append** their findings;
  * a node returning `Replace([...])` **overwrites** them. The planner uses this to
    clear the previous chat turn, and the validator uses it to swap in cleaned findings.

  A plain `operator.add` would let findings pile up across chat turns.

### Skill sub-agent (`graph/nodes/skill_runner.py`)
```
START → agent ⇄ tools (ToolNode)   … until no more tool calls or step cap
          └──► respond (structured output → SkillFinding) → END
```
* **System prompt** = common research rules + the skill's `SKILL.md` body.
* **Tools** = only those listed in the skill's frontmatter (least privilege).
* **Two-phase output.** Research turns are free-form. A final `respond` call converts the
  transcript into a schema-validated `SkillFinding`. Forcing JSON on every turn degrades
  tool use, so research and output are kept separate.
* **Failure isolation.** Any exception becomes an *error finding*. The brief still
  completes, and the failure appears in the report's data-quality notes.

### Progressive disclosure
1. The planner sees only `name` and `description` for each skill, which keeps routing
   prompts small.
2. A selected skill's full Markdown body is loaded only into its own sub-agent.
3. Detailed source documents are fetched only when needed (`fetch_document` with
   `focus` keywords trims long PDFs).

## Data model
Every skill returns one `SkillFinding` (metrics, signals, citations, narrative). Shared
vocabularies for metric keys, units and submarkets let figures from different skills and
brokers line up in history, deltas and charts. All structures are documented field by
field in [DATA_MODEL.md](DATA_MODEL.md): domain models, graph state, `SKILL.md`
frontmatter, the SQLite schema and fixture formats.

## Metric history (`store/metrics.py`)
Append-only SQLite table.

* `series()` returns one value per (submarket, period, **source**), and the latest run
  wins, so revisions are respected. Sources are kept apart because brokers' definitions differ.
* `deltas()` compares only **different periods**. Same-period differences are source
  disagreements, and the validator handles them.
* `deltas()` **prefers same-source history**. A cross-source change (e.g. BNP 8.4% → Avison
  Young 6.3% vacancy) is used only as a fallback, and it is labelled "not like-for-like"
  in the report.
* Immaterial moves (under 0.1pp, or under 0.5%) are hidden from "what changed".

On first use, the store is seeded from `fixtures/history.json`, so trend charts work
from day one.

## Persistence
* Numbers go to an append-only SQLite table (`data/metrics.sqlite`) after validation, on
  every brief and chat turn.
* Briefs write HTML, Markdown, per-run PNG charts and a findings JSON audit trail to
  `reports/<date>/`.
* Chat memory lives in LangGraph's checkpointer (`data/checkpoints.sqlite`) per thread.
  A separate conversation index (`data/conversations.sqlite`) records titles and per-turn
  details. That powers the sidebar history, where past chats can be reopened and
  resumed, and `cre-monitor conversations`.

Full table, column schema and reading rules:
[DATA_MODEL.md §6](DATA_MODEL.md#6-persistence-what-is-stored-where).

## Testability
* Deterministic logic is kept separate from the LLM.
* Offline and demo modes make the whole graph reproducible.
* A scripted fake LLM is injected through `get_llm()`.
* The UI is tested headlessly, live smoke tests are opt-in, and an eval set covers
  model behaviour.

Details, per-file coverage and how to add tests: [TESTING.md](TESTING.md).

## Modes (`config.py`)
* `CRE_OFFLINE`: tools read `fixtures/` instead of the network.
* `CRE_DEMO_MODE`: no LLM. Skills return fixture findings, and synthesis and chat answers
  are rule-based. It turns on automatically when no Anthropic key is set.

## Reporting (`reporting/`)
Plotly figures follow the team's data-viz rules (documented in `charts.py`):
* the colour follows the entity (fixed submarket colours);
* palette slots are validated;
* one y-axis per chart;
* direct labels on lines;
* interactive hover in HTML.

The Jinja2 templates render HTML (interactive) and Markdown (with PNGs via kaleido;
PNG export failure is non-fatal).

## Extension points
| Want to... | Do this |
|---|---|
| Add a research area | New `skills/<name>/SKILL.md` ([guide](SKILLS.md)) |
| Add a data source | New `@tool` in `tools/` with an offline fixture path; register in `tools/__init__.py`; list it in skills' `tools` |
| Add a metric | Add the key + unit to `schemas.METRIC_KEYS`; reference it in a skill's `metrics` / `sanity_ranges` |
| Add a chart | New function in `reporting/charts.py`, register in `build_charts` |
| Change models | `.env`: `MODEL_ROUTER`, `MODEL_SKILL`, `MODEL_SYNTHESIS` |
| Deliver reports elsewhere | Add a node after `report_writer` (e.g. email/Teams) |

## Production hardening (not in PoC scope)
* Postgres for metrics and checkpoints. A hosted scheduler (Azure Functions, Airflow) instead of Task Scheduler.
* LangSmith tracing and evaluation datasets. Cost dashboards.
* Paid data feeds (CoStar, EGi, PMA) as additional tools. Licensing review for broker content.
* Authentication on the UI. Report distribution lists.
