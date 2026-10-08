# Testing and evaluation

How the agent is made testable, what each test covers, and how to add tests. Commands
are summarised in [USAGE.md §3](USAGE.md#3-tests-and-evaluations).

- [1. What "testable" means here](#1-what-testable-means-here)
- [2. Techniques that make it testable](#2-techniques-that-make-it-testable)
- [3. Test layers](#3-test-layers)
- [4. Test files](#4-test-files)
- [5. The fake LLM](#5-the-fake-llm-testsfake_llmpy)
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
| **Test isolation** | `tests/conftest.py` sets offline + demo mode, blanks the keys, points `DATA_DIR`/`REPORTS_DIR`/`EXPORTS_DIR`/`STYLE_DIR` at a temp folder, disables PNG export and clears all cached singletons per test. Safety net: `ANTHROPIC_BASE_URL` points at a closed local port, so a test that builds a real Claude client by mistake fails in seconds instead of spending credit | Tests never touch real history or the repo's style profile, never call the real API, and don't leak state |
| **Audit trail** | `findings_<run>.json`, data-quality notes in the report, logs | Live runs can be inspected afterwards |

## 3. Test layers

| Layer | What runs | Where |
|---|---|---|
| Unit | Pure functions (validator rules, deltas, chart selection, focus-text trimming, conversation grouping, style layout and number guard) | `test_validator`, `test_store`, `test_charts`, `test_tools`, `test_conversations`, `test_style` |
| Contract | Every skill loads and conforms; invalid skills are rejected, not crashed | `test_skills` |
| Integration (tools) | Each LangChain tool via its public interface, on fixtures | `test_tools` |
| End to end (demo) | Full graph: brief and multi-turn chat, report files, PNGs, same-day runs | `test_graph` |
| End to end (LLM path) | Real ReAct sub-agent + router + synthesis, driven by the fake LLM | `test_graph` (`fake_llm` fixture) |
| UI | Streamlit app rendered headlessly; a chat turn simulated | `test_ui` |
| Live smoke (opt-in) | Real BoE, ONS, Nomis, Google News, Tavily; one real skill if a key is set | `test_live` (`-m live`) |
| Evaluation | Routing, grounding, citations over a question set | `evals/run_evals.py` |

## 4. Test files

`pytest` runs 191 offline tests in about 60-90 s. `pytest -m live` runs 7 more.

| File | Tests | Covers |
|---|---|---|
| `test_skills.py` | 4 | All repo skills valid; brief order and instructions present; router catalogue shows descriptions only; invalid skills (wrong name, unknown metric, unknown tool) reported, not raised |
| `test_tools.py` | 7 | `web_search`, `fetch_document` (incl. unknown URL), `rss_news`, `boe_series`/`ons_series` (incl. unknown series), `metrics_history`, paragraph focusing |
| `test_validator.py` | 8 | Clean pass; out-of-range dropped; unit / unknown key / non-canonical submarket warnings; aliases mapped to catalogue names (Docklands → Canary Wharf); missing URL and stale data; cross-source conflicts flagged (and small differences not flagged); failed skills reported |
| `test_store.py` | 5 | Latest run wins per period; deltas only across periods; same-source preference and cross-source labelling; readable number formatting; seeding |
| `test_charts.py` | 5 | Single-source preference for trends; mixed-source fallback flagged and dashed; consistent source in bar charts; full chart set built from history |
| `test_graph.py` | 15 | Demo brief end to end (HTML/MD sections, PNGs, no HTML escaping in Markdown); deltas vs seeded history; skill subset; unknown skill rejected; keyword routing; multi-turn chat resets findings but keeps messages; same-day briefs keep their own charts; **fake-LLM**: real sub-agent calls tools and submits a finding via `submit_finding`; **regression: one tool list per skill and a strictly append-only conversation** (the live thinking-signature 400); plain-text answer → nudge → submit; invalid submission → error tool result → resubmit; step budget → wrap-up; never submitting → error finding; router drops unknown skills; **referenced conversations reach the router and answer prompts (with precedence rules) but never a research skill's prompt** |
| `test_conversations.py` | 10 | Conversation store: record, list, redraw turns, rename, delete; titles; recency grouping; `ask()` records turns and resume keeps agent memory; delete removes index and memory; **context packs** (dated, excerpted, figures listed, capped to recent turns/size); old database upgraded with the `refs_json` column; `resolve_refs` drops self/unknown/duplicates and caps at 3; refs are used, recorded and don't carry over to the next turn |
| `test_ui.py` | 11 | App renders all tabs; a chat turn returns an answer with skills shown; a conversation is listed in the sidebar (titled, in the URL), New chat clears it and clicking it restores it; a fresh session opens a conversation from `?thread=`; the reference picker lists other chats and the answer shows "📎 Referenced"; **an API failure shows the styled error panel, a valid `ERR-` reference, the support contact, and no raw error text in the answer**; deleting a brief from the Briefs tab removes it and confirms; sidebar export builds the zip and offers the download; **🎨 House style panel**: learn, show, delete an example, clear (uploads go through `save_example`, unit-tested in `test_style`, because AppTest can't drive `st.file_uploader`); **Run full brief now** honours the **Use house style** toggle; **partial brief**: None disables the button, ticked skills change the label and only they run, All restores the full brief |
| `test_errors.py` | 16 | **Reports**: a partial failure shows the amber panel, plain-English title, per-skill "Not available" line, the same `ERR-` reference as the run, the support contact, and **no raw error text outside the engineers' section** (HTML and Markdown), while the findings JSON keeps the audit trail; a total failure shows the red panel. Classification of real error texts (incl. the exact 403 and the live thinking-signature 400 seen in practice) into 9 categories; reference ID format; incidents logged with the reference, thread and raw errors; most actionable category wins; exception → total incident; **end to end with every LLM call refused**: chat gives a clean answer plus a total incident saved with the turn; a brief reports an incident and keeps raw text out of the report |
| `test_briefs.py` | 12 | Deleting one of two same-day briefs keeps the other; empty date folder removed; legacy shared charts removed only with the last brief; invalid ids (incl. path traversal) and unknown ids rejected; `--with-metrics` removes only that run's rows and keeps the seed; the default keeps metrics; the seed cannot be deleted; CLI `briefs list` / `delete --yes` / confirmation prompt |
| `test_export.py` | 6 | Zip structure; metrics rows match the store; briefs copied and indexed; transcripts include references and error IDs; `conversations.json` structure; Excel sheets and row counts; manifest; **no API key anywhere in the export**; `--since` filtering (seed only in full exports); logs only on request; empty installation; CLI date validation and export |
| `test_merge.py` | 17 | Real second installation merged into the target: everything added and **merged chats resume with their memory**; re-running changes nothing; a continued conversation is extended (memory includes the new turn); same id with different history is renamed, references are remapped and memories kept apart; seed not duplicated; **dry run writes nothing yet reports exactly what the real merge does**; pre-merge backup holds the old state; invalid / own-folder sources rejected; old-schema source; brief file conflicts keep the target's file; CLI dry-run, preview/decline, `--yes`. **All-or-nothing**, each comparing full database contents before and after: failure after a partial commit → restored byte-for-byte; failure while copying briefs → DBs restored and the copy removed; failure while preparing → nothing changed, no backup; target locked by another writer → "in use", nothing changed; failure on a fresh target → created databases removed; CLI shows "Merge failed … restored" with an `ERR-` reference |
| `test_style.py` | 14 | House style: saving/deleting example files stays inside `style/reports/` (path traversal, unsupported types, README rejected); heuristic learning (layout, voice, number conventions, techniques; README ignored; profile saved as JSON + Markdown); LLM learning sends bounded excerpts; no examples → clear error; HTML examples read; layout resolution (order, headings, duplicates ignored, **no section ever dropped**, missing sections placed before the reference sections); a brief follows the house layout, and both the per-run switch (`use_style=False`) and `REPORT_STYLE=0` turn it off (also for the synthesis prompt); **number guard** (restyled text may not add or change figures); style editor restyles, keeps the original when the guard trips, leaves failed findings and metrics untouched, and survives an LLM failure; the synthesis prompt carries the profile with "facts take priority"; CLI `style learn/show/clear` and `brief --no-style` |
| `test_catalog.py` | 8 | Repo catalogue consistent with skills and code (protected keys exist, tracked defaults, aliases); adding a metric writes the file with its header, keeps the old version in history and unlocks the key for skills; bad keys and duplicate keys/labels rejected; **concurrent edits refused** (`ConflictError`); tracking/updating; protected and skill-used metrics can't be removed; submarket add/update/remove incl. alias clashes and protected places; new metrics and submarkets reach the research prompt |
| `test_dashboard.py` | 9 | **Periods**: parsing (Q/H/month/year/week/day), true time order ("2026-H1" after "2026-Q1"), same-frequency check; **deltas never compare a half-year with a quarter**; formatting by unit (£ psf, %, m/k sq ft, £bn/£m, pp/% change); a line follows one source and one period length, falls back to dashed "mixed sources", respects a chosen source; latest-by-submarket and headline (same source + length for the change); ≤4 places overlaid on a date axis, more as small multiples; new places get unused colours. **UI**: tracked headline cards, no submarket cap, switching metrics; untracking hides a card and saves the catalogue; add/remove a submarket with aliases; protected places have no delete button |
| `test_skill_editor.py` | 8 | Every repo skill round-trips through the editor and validates; save keeps history, rebuilds the registry, **refuses stale saves**, and restoring a version works; validation messages are plain English (name, tools, unknown metrics, short instructions, ranges without metric, duplicate name); a new skill joins the brief and runs in demo mode ("No demo data"); delete → trash → restore, orphaned metrics, protected `market-synthesis`, restore name clash; **path tricks refused**; attach/detach a metric across skills; no git noise outside the repo |
| `test_authoring.py` | 8 | Exact catalogue matches need no LLM (work in demo mode); unknown requests need live mode; **needs a skill change** → catalogue entry + skill update; **model answers re-validated** (unknown skill → not feasible, existing key → already collected, ghost key → not feasible); not feasible changes nothing; failed skill write **rolls back** the catalogue entry; test run reports whether the metric came back; skill drafts drop unknown tools/metrics and list missing metrics; review |
| `test_ui_authoring.py` | 6 | Skills tab: edit + save (history kept); validation errors shown and nothing saved; create from blank template, opened after creation, delete and restore; protected skill has no delete button. Add a metric: existing name → Track it (demo mode), unknown name in demo → needs Claude; with the fake LLM, **nothing saved before approval**, the proposal is editable, approval updates catalogue and skill |
| `test_benchmark.py` | 14 | Performance check: numbers found in any format ("2.6m sq ft", "£1.2bn", "6.3%"; period labels ignored); scoring (coverage, accuracy, same vs other source, missing, **grounding**, tolerances); readability ordering; answer-key **signals** (in document, catalogue, period, confidence → safe), stable ids, accept-safe, storage; library roles; AI key extraction (signals computed, duplicates dropped) and live-mode requirement; run planning (one skill covers several figures, not-collectable figures) and **tasks never reveal the expected values**; **full figure run with the fake LLM** (scores, grounding catches an invented figure, citation check against a fixture page, token cost, over-target warning, history); optional cap only when set; brief judgement free statistics in demo mode and the AI rubric; CLI `bench` commands |
| `test_ui_reference.py` | 5 | 📚 Reference reports tab: house style moved from the sidebar, library role ticks saved; answer-key moderation tiles + Accept all safe, AI steps need live mode in demo; `apply_edits` (corrected value rechecked, invalid status refused); figure run scorecard tiles and cost warning; brief judgement in demo mode |
| `test_cli.py` | 3 | `cre-monitor ui` passes `toolbarMode=viewer` by default, and `developer` with `--debug` or `CRE_UI_DEBUG=1` (Streamlit launch is captured, not run) |
| `test_live.py` | 7 (opt-in) | BoE Bank Rate; ONS CPIH / unemployment / GDP; Nomis London employment; Google News + search; one real `macro-economy` skill run (needs `ANTHROPIC_API_KEY`) |

## 5. The fake LLM (`tests/fake_llm.py`)

`ScriptedChatModel` is a LangChain chat model that:
* plays back a list of pre-written `AIMessage`s. These can contain **real tool calls**,
  which LangGraph's `ToolNode` then executes against the offline fixtures;
* returns pre-built objects for structured-output calls, keyed by schema name
  (`SkillFinding`, `SkillSelection`, `ExecutiveSynthesis`);
* records every prompt it receives in `.calls`, so tests can check what the agent
  actually sent.

The `fake_llm` fixture in `test_graph.py` turns demo mode off and patches `get_llm` in
every node module. One test then asserts that:
* the sub-agent executed both scripted tool calls, and their fixture results reached the
  model's next turn;
* the system prompt contained the skill's `SKILL.md` instructions;
* the final finding is the structured object, with `skill` overwritten correctly;
* the synthesis step produced the report.

This verifies the full agent wiring without spending tokens. It does not verify Claude's
judgement; that is what the evaluations are for.

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

| You changed… | Add / update |
|---|---|
| A new skill | `fixtures/findings/<skill>.json`; add the name to `EXPECTED_RESEARCH_SKILLS` in `test_skills.py`; optionally an eval question |
| A new tool | A fixture path in the tool, plus a test in `test_tools.py` using `TOOLS["name"].invoke({...})` |
| Validator rules | A case in `test_validator.py` using the `metric()` / `finding()` helpers |
| Delta / history logic | `test_store.py` with a temp `MetricsStore(tmp_path / "m.sqlite")` |
| Charts | `test_charts.py`: assert on the selected data or figure properties, not pixels |
| Agent flow / prompts | A `ScriptedChatModel` script in `test_graph.py` (see the `fake_llm` fixture) |
| UI | `AppTest.from_file(...)` in `test_ui.py` |
| Anything hitting the network | Mark with `@pytest.mark.live` so the default run stays offline |

Conventions:
* Tests must pass offline with no keys.
* Don't write to the real `data/` or `reports/`; the autouse fixture handles this.
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
