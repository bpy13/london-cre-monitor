# Testing and evaluation

How the agent is made testable, what each test covers, and how to add tests. Commands
are summarised in [USAGE.md §3](USAGE.md#3-tests-and-evaluations).

- [1. What "testable" means here](#1-what-testable-means-here)
- [2. Techniques that make it testable](#2-techniques-that-make-it-testable)
- [3. Test types and layout](#3-test-types-and-layout)
- [4. Test files](#4-test-files)
- [5. The fake LLM](#5-the-fake-llm-testssupportfake_llmpy)
- [6. Evaluations](#6-evaluations-evals)
- [7. Writing new tests](#7-writing-new-tests)
- [8. Known gaps](#8-known-gaps)

---

## 1. What "testable" means here

An LLM agent is testable when its behaviour can be checked:

1. **Automatically and repeatably:** same input, same result, so a red test means a real regression.
2. **Cheaply and offline:** no network, no API keys and no token spend, so every
   developer can run the full suite in seconds.
3. **At every level:** individual functions, the tools, the whole graph and the UI.
4. **With model-dependent behaviour measured, not assumed:** the parts that depend on
   Claude's judgement (routing, grounding, citing) are scored by an evaluation set that
   can also run against the real model.
5. **Measured against reality:** the **performance check** scores the live agent's figures
   and briefs against reference reports your team trusts. It covers coverage, accuracy,
   grounding, citations and a brief-quality rubric. See [EVALUATION.md](EVALUATION.md).

## 2. Techniques that make it testable

| Technique | How it is implemented | What it enables |
|---|---|---|
| **Deterministic logic kept out of the LLM** | Validation, deltas, history, chart data selection and rendering are pure Python (`validator.validate`, `MetricsStore.deltas`, `charts.pick_series`, …) | Plain unit tests with exact assertions |
| **Typed contracts** | Every skill returns a Pydantic `SkillFinding`; every `SKILL.md` frontmatter is validated by `SkillMetadata` | Bad LLM output or broken skills fail loudly and early |
| **Offline mode** (`CRE_OFFLINE=1`) | Every tool has a fixture path (`fixtures/`) | Repeatable tool tests and graph runs without the internet |
| **Demo mode** (`CRE_DEMO_MODE=1`) | Skills return `fixtures/findings/*.json`; synthesis and chat answers are rule-based | The **whole graph** runs end to end with the same result every time |
| **Dependency injection** | Every model comes from `get_llm()`, which tests patch | A scripted fake LLM drives the **real** agent code (see §5) |
| **Failure isolation** | A skill exception becomes an error finding instead of crashing the run; all failures become one `Incident` with a reference ID | Failure paths are observable and assertable, including what users see |
| **Test isolation** | `tests/conftest.py` sets offline + demo mode, blanks the keys, points `DATA_DIR`/`REPORTS_DIR`/`EXPORTS_DIR`/`STYLE_DIR` at a temp folder, copies `skills/` and `catalog/` there (`SKILLS_DIR`/`CATALOG_DIR`), disables PNG export and clears all cached singletons per test. Safety net: `ANTHROPIC_BASE_URL` points at a closed local port, so a test that builds a real Claude client by mistake fails in seconds instead of spending credit | Tests never touch real history or the repo's style profile, never call the real API, and don't leak state |
| **Audit trail** | `findings_<run>.json`, data-quality notes in the report, logs | Live runs can be inspected afterwards |

## 3. Test types and layout

Tests are grouped by **type**, one folder each. Every test is automatically tagged with
its folder's marker (`tests/conftest.py`), so both forms below select the same tests:

| Type | Folder / marker | What it checks | Speed |
|---|---|---|---|
| **Unit** | `tests/unit/` · `-m unit` | One module in isolation: pure functions, or the module's own temporary files. No graph runs, no CLI, no fake LLM | 79 tests, ~4 s |
| **Integration** | `tests/integration/` · `-m integration` | Several components together: the skill agent and Claude-assisted features driven by the fake LLM, stores with real files, export/merge between installations, CLI commands | 71 tests |
| **End to end** | `tests/e2e/` · `-m e2e` | User journeys through the whole LangGraph pipeline: a brief or chat turn from start to finish, in demo mode or with every LLM call failing | 13 tests |
| **UI** | `tests/ui/` · `-m ui` | The Streamlit app, run headlessly with `AppTest` | 24 tests |
| **Regression** | `tests/regression/` · `-m regression` | Reproductions of bugs that were found and fixed (table in `test_fixed_bugs.py`) | 4 tests |
| **Live** | `tests/live/` · `-m live` | Real BoE, ONS, Nomis, Google News, Tavily; one real skill run if a key is set. Deselected by default | 7 tests (opt-in) |
| Evaluation | `evals/run_evals.py` | Routing, grounding and citations over a question set (demo or live) | – |
| Performance check | `cre-monitor bench` | The live agent against reference reports ([EVALUATION.md](EVALUATION.md)) | – |

```bash
pytest                      # all offline types (191 tests, ~50-90 s)
pytest tests/unit           # fastest feedback while coding (or: pytest -m unit)
pytest -m "unit or regression"
pytest -m "not ui"          # skip the slower Streamlit tests
pytest -m live              # live smoke tests (needs keys and network)
```

Shared test code lives in `tests/support/` (not collected as tests):

| File | Contents |
|---|---|
| `support/fake_llm.py` | `ScriptedChatModel`, `submit_call()`, `tool_call()` (see §5) |
| `support/fixtures.py` | Fixtures available to every test via `pytest_plugins`: `fake_llm`, `examples` (two style example reports), `api_refuses` (every LLM call fails with the real 403) |
| `support/samples.py` | Shared sample data and builders: `REPORT`, `AY_URL`, `key_entry()`, `agent_metric()`, `run_key()`, `script_benchmark_skill()`, `EXAMPLE_A/B`, `style_finding()`, `skill_draft()`, `REAL_403` |
| `support/apptest.py` | `APP`, `run_app()`, `button_labelled()`, `assistant_text()` for UI tests |

## 4. Test files

`pytest` runs 191 offline tests. `pytest -m live` runs 7 more.

### Unit (`tests/unit/`)
| File | Tests | Covers |
|---|---|---|
| `test_validator.py` | 8 | Clean pass; out-of-range dropped; unit / unknown key / non-canonical submarket warnings; aliases mapped to catalogue names (Docklands → Canary Wharf); missing URL and stale data; cross-source conflicts flagged (small differences not); failed skills reported |
| `test_metrics_store.py` | 4 | Latest run wins per period; deltas only across periods; readable number formatting; seeding |
| `test_charts.py` | 5 | Single-source preference for trends; mixed-source fallback flagged and dashed; consistent source in bar charts; full chart set built from history |
| `test_periods.py` | 1 | Period parsing (Q/H/month/year/week/day), true time order ("2026-H1" after "2026-Q1"), same-frequency check |
| `test_dashboard_data.py` | 4 | Formatting by unit (£ psf, %, m/k sq ft, £bn/£m, pp/% change); a line follows one source and one period length, falls back to dashed "mixed sources", respects a chosen source; latest-by-submarket and headline; ≤4 places overlaid on a date axis, more as small multiples; new places get unused colours |
| `test_scoring.py` | 3 | Numbers found in any format; figure scoring (coverage, accuracy, same vs other source, missing, **grounding**, tolerances); readability |
| `test_answer_key.py` | 3 | Answer-key **signals** (in document, catalogue, period, confidence → safe), stable ids, accept-safe, storage; run planning (one skill covers several figures, not-collectable figures) and **tasks never reveal the expected values**; `apply_edits` (corrected value rechecked, invalid status refused) |
| `test_catalog.py` | 8 | Repo catalogue consistent with skills and code; adding a metric (file header, history, unlocks the key for skills); bad/duplicate entries rejected; **concurrent edits refused**; tracking/updating; protected and skill-used metrics can't be removed; submarket add/update/remove incl. alias clashes; new metrics and submarkets reach the research prompt |
| `test_skill_registry.py` | 4 | All repo skills valid; brief order and instructions present; router catalogue shows descriptions only; invalid skills reported, not raised |
| `test_tools.py` | 7 | `web_search`, `fetch_document` (incl. unknown URL), `rss_news`, `boe_series`/`ons_series`, `metrics_history`, paragraph focusing - all on offline fixtures |
| `test_errors.py` | 4 | Classification of real error texts (incl. the exact 403 and the live thinking-signature 400) into 9 categories; reference ID format; incidents logged with reference, thread and raw errors; exception → total incident |
| `test_conversations_store.py` | 7 | Store: record, list, redraw, rename, delete; titles; recency grouping; **context packs** (dated, excerpted, figures listed, capped); old database upgraded with `refs_json`; `resolve_refs` drops self/unknown/duplicates and caps at 3 |
| `test_style_profile.py` | 8 | Heuristic learning (layout, voice, number conventions, techniques; README ignored; JSON + Markdown); no examples → clear error; HTML examples read; example files stay inside `style/reports/`; library roles; layout resolution (**no section ever dropped**); **number guard** |
| `test_skill_editor.py` | 4 | Every repo skill round-trips through the editor; plain-English validation messages; **path tricks refused**; no git noise outside the repo |
| `test_routing.py` | 1 | Keyword (fallback) routing |

### Integration (`tests/integration/`)
| File | Tests | Covers |
|---|---|---|
| `test_skill_agent.py` | 5 | The real ReAct sub-agent with the fake LLM: calls tools and submits via `submit_finding` (tool results reach the next turn, SKILL.md in the prompt); plain-text answer → nudge → submit; invalid submission → error tool result → resubmit; step budget → wrap-up; never submitting → error finding |
| `test_router.py` | 2 | Router drops unknown skills; **referenced conversations reach the router and answer prompts (with precedence rules) but never a research skill's prompt** |
| `test_authoring.py` | 8 | Metric feasibility: exact matches need no LLM; **needs a skill change** → catalogue + skill; **model answers re-validated**; not feasible changes nothing; failed skill write **rolls back** the catalogue entry; test run; skill drafts drop unknown tools/metrics; review |
| `test_benchmark_runs.py` | 7 | AI answer-key extraction (signals computed, duplicates dropped) and live-mode requirement; **full figure run with the fake LLM** (scores, grounding catches an invented figure, citation check against a fixture page, token cost, over-target warning, history); optional cap only when set; brief judgement (free statistics in demo mode, AI rubric) |
| `test_style_apply.py` | 4 | LLM style learning sends bounded excerpts; style editor restyles but the guard keeps originals when figures change; editor failure keeps findings; the synthesis prompt carries the house style with "facts take priority" (and not when switched off) |
| `test_skill_editor_effects.py` | 4 | Save keeps history, rebuilds the registry, **refuses stale saves**, restore works; a new skill joins the brief and runs in demo mode; delete → trash → restore, orphaned metrics, protected `market-synthesis`; attach/detach a metric across skills |
| `test_briefs.py` | 9 | Deleting one of two same-day briefs keeps the other; legacy shared charts; invalid/unknown ids rejected; `--with-metrics` vs default; seed protected; CLI `briefs list` / `delete --yes` / confirmation |
| `test_export.py` | 6 | Zip structure and contents; **no API key anywhere in the export**; `--since` filtering; logs only on request; empty installation; CLI |
| `test_merge.py` | 17 | Real second installation merged: merged chats resume with their memory; idempotent; continued conversations extended; id clashes renamed with references remapped; seed not duplicated; **dry run reports exactly what the merge does**; backup; invalid / old-schema sources; brief file conflicts; **all-or-nothing** on every failure point (byte-for-byte restore, locked target, fresh target); CLI |
| `test_cli.py` | 6 | `cre-monitor ui` toolbar mode (default, `--debug`, `CRE_UI_DEBUG=1`; launch captured); `style learn/show/clear`; `brief --no-style`; `bench` commands in demo mode |

### End to end (`tests/e2e/`)
| File | Tests | Covers |
|---|---|---|
| `test_brief.py` | 8 | Demo brief end to end (HTML/MD sections, PNGs, no HTML escaping in Markdown); deltas vs seeded history; skill subset; unknown skill rejected; house layout (and switched off per run / by `REPORT_STYLE=0`); **failures**: amber panel for a partial failure, red panel when nothing usable, no raw error text outside the engineers' section, same `ERR-` reference as the run, a brief with every LLM call refused |
| `test_chat.py` | 5 | Multi-turn chat resets findings but keeps messages; `ask()` records turns and resume keeps agent memory; references used, recorded and not carried over; deleting a conversation removes index and memory; chat with every LLM call refused gives a clean answer and an incident saved with the turn |

### UI (`tests/ui/`)
| File | Tests | Covers |
|---|---|---|
| `test_app.py` | 11 | Tabs render; chat turn with skills shown; conversations listed, reopened, opened from `?thread=`; reference picker; **API failure shows the styled panel with an `ERR-` reference and no raw text**; delete a brief; sidebar export; house style learn/show/delete/clear and the Use-house-style toggle; **partial brief** tick boxes |
| `test_dashboard_tab.py` | 3 | Tracked headline cards, no submarket cap, switching metrics; untracking hides a card and saves the catalogue; add/remove a submarket with aliases, protected places have no delete button |
| `test_skills_and_metrics_ui.py` | 6 | Skills tab: edit + save, validation errors (nothing saved), create from template → delete → restore, protected skill; Add a metric: Track it (demo), needs Claude (demo), with the fake LLM nothing saved before approval and the proposal is editable |
| `test_reference_tab.py` | 4 | Reference reports tab: house style moved from the sidebar, library roles saved; answer-key moderation + Accept all safe, AI steps need live mode; figure run scorecard and cost warning; brief judgement in demo mode |

### Regression (`tests/regression/`)
| File | Tests | Covers |
|---|---|---|
| `test_fixed_bugs.py` | 4 | The live thinking-signature 400 (one tool list, append-only conversation); same-day briefs overwriting each other's charts; cross-source deltas presented as market moves; half-year vs quarter deltas and text ordering of periods |

### Live (`tests/live/`, opt-in)
| File | Tests | Covers |
|---|---|---|
| `test_live.py` | 7 | BoE Bank Rate; ONS CPIH / unemployment / GDP; Nomis London employment; Google News + search; one real `macro-economy` skill run (needs `ANTHROPIC_API_KEY`) |

## 5. The fake LLM (`tests/support/fake_llm.py`)

`ScriptedChatModel` is a LangChain chat model that:
* plays back a list of pre-written `AIMessage`s. These can contain **real tool calls**,
  which LangGraph's `ToolNode` then executes against the offline fixtures;
* returns pre-built objects for structured-output calls, keyed by schema name
  (`SkillSelection`, `ExecutiveSynthesis`, `MetricAssessment`, …);
* records every prompt it receives in `.calls`, so tests can check what the agent
  actually sent.

The `fake_llm` fixture (`tests/support/fixtures.py`, available everywhere) turns demo mode
off and patches `get_llm` in every node module and in `cre_monitor.llm`. The skill-agent
integration tests then assert that:
* the sub-agent executed both scripted tool calls, and their fixture results reached the
  model's next turn;
* the system prompt contained the skill's `SKILL.md` instructions;
* the final finding is the structured object, with `skill` overwritten correctly;
* the synthesis step produced the report.

This verifies the full agent wiring without spending tokens. It does not verify Claude's
judgement; that is what the evaluations and the performance check are for.

## 6. Evaluations (`evals/`)

`questions.yaml` holds 7 chat questions, one or more per skill area. For each, `run_evals.py` checks:
* **Routing:** the expected skills were selected.
* **Grounding:** the answer contains the expected facts (`must_contain`).
* **Citation:** the answer includes at least one source link.

```bash
python evals/run_evals.py          # demo + offline: deterministic, free (7/7 expected)
python evals/run_evals.py --live   # real agent + live data: measures actual model behaviour
```

The runner exits non-zero on any failure, so it can gate prompt or skill changes. It
uses a temp data folder, so evals never pollute the real metrics history. For live runs,
update `must_contain` when fixtures and quarters change.

## 7. Writing new tests

| You changed… | Add / update (which type) |
|---|---|
| A pure function (validator rule, delta, chart selection, scoring, parsing) | **Unit**: the matching file in `tests/unit/` |
| A new skill | `fixtures/findings/<skill>.json`; add the name to `EXPECTED_RESEARCH_SKILLS` in `unit/test_skill_registry.py`; optionally an eval question |
| A new tool | A fixture path in the tool, plus a **unit** test in `unit/test_tools.py` using `TOOLS["name"].invoke({...})` |
| Agent flow / prompts | **Integration**: a `ScriptedChatModel` script in `integration/test_skill_agent.py` or `test_router.py` (use the `fake_llm` fixture) |
| Several components / files / CLI | **Integration**: the feature's file in `tests/integration/` |
| A whole user journey (brief, chat) | **E2E**: `e2e/test_brief.py` or `e2e/test_chat.py` |
| UI | **UI**: `run_app()` from `tests/support/apptest.py` in the tab's file in `tests/ui/` |
| You fixed a bug | **Regression**: a test reproducing it in `regression/test_fixed_bugs.py`, plus a row in its table |
| Anything hitting the network | **Live**: `tests/live/` (deselected by default) |
| Sample data used by several files | `tests/support/samples.py` (fixtures: `tests/support/fixtures.py`) |

Conventions:
* Tests must pass offline with no keys.
* Don't write to the real `data/`, `reports/`, `skills/` or `catalog/`; the autouse fixture
  points them at a temporary folder.
* Put a test in the folder of its type; never import from another test module - shared
  code belongs in `tests/support/`.
* If you add a new cached singleton, clear it in `conftest._clear_caches`.

## 8. Known gaps

* **The live Claude path has never run end to end.** It has only been exercised with the
  fake LLM, because the API was not reachable from the development location. Run
  `pytest -m live` and `python evals/run_evals.py --live` from a supported location
  before relying on live output.
* **Evals are string-based.** They don't use an LLM judge, so they can miss wrong but
  plausible answers.
* **No tracing** (e.g. LangSmith) for live runs, and no cost assertions.
* **No CI pipeline** is configured yet. A GitHub Actions workflow running `pytest` on
  each push is the obvious next step.
