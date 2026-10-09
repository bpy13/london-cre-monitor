# Data model and persistence

Every data structure in the system, how they relate, and what is stored where. The
source of truth is the code: `src/cre_monitor/schemas.py` (domain models),
`graph/state.py` (graph state), `skills/registry.py` (skill metadata),
`store/metrics.py` and `store/conversations.py` (SQLite schemas).

- [1. Overview](#1-overview)
- [2. Controlled vocabularies](#2-controlled-vocabularies-the-catalogue)
- [3. Domain models](#3-domain-models-schemaspy)
- [4. Graph state](#4-graph-state-graphstatepy)
- [5. Skill definition](#5-skill-definition-skillsnameskillmd)
- [6. Persistence: what is stored where](#6-persistence-what-is-stored-where)
- [7. Fixture formats](#7-fixture-formats-fixtures)

---

## 1. Overview

```
Skill sub-agent ──► SkillFinding ─┬─ metrics[]  : Metric      ──► validator ──► persist ──► metrics.sqlite (one row per Metric)
                                  ├─ signals[]  : Signal                                       │
                                  ├─ citations[]: Citation                                     ▼
                                  ├─ headline, summary, insights[], confidence, error      MetricDelta[] ("what changed")
                                  │
       all findings + deltas + ValidationIssue[] ──► synthesis ──► ExecutiveSynthesis ──► report_writer ──► reports/<date>/
```

* **`SkillFinding`** is the single output contract of every skill, whatever its topic.
  Validation, storage, charts and reports only ever see `SkillFinding` objects. That is
  what lets new skills plug in without code changes.
* All models are **Pydantic v2** classes. They validate LLM output, give structured-output
  JSON schemas to Claude, and serialise to JSON for the audit trail.

## 2. Controlled vocabularies (the catalogue)

Shared vocabularies make figures from different skills and brokers line up in history,
deltas and charts. They are **data, not code**: two YAML files in `catalog/`, loaded by
`cre_monitor/catalog.py`, editable by hand or from the UI (Dashboard → Manage metrics /
Manage submarkets). The research prompt lists them, skills may only declare catalogue
metrics, and the validator flags anything else.

### Metric catalogue (`catalog/metrics.yaml`, `MetricDef`)
| Field | Type | Notes |
|---|---|---|
| `key` | str | snake_case, 3-60 chars; stored with every figure; never renamed |
| `label` | str | Plain-English name shown in the UI, unique (case-insensitive) |
| `unit` | str | Expected unit; a mismatch triggers a validator warning |
| `group` | str | Dashboard grouping: Rents, Vacancy & availability, Leasing, Supply pipeline, Investment, Occupier demand, Macro |
| `definition` | str | What exactly is measured (shown in the UI and to the add-metric assessment) |
| `tracked` | bool | Shown on the Dashboard by default |
| `added_at` | str | Set when added through the UI |

The original 31 metrics:

| Group | Keys (unit) |
|---|---|
| Rents | `prime_rent`, `grade_a_rent` (GBP psf pa); `rent_free_months` (months); `prime_rent_growth_yoy` (%) |
| Vacancy | `vacancy_rate`, `new_build_vacancy_rate`, `grade_a_share_of_availability` (%); `availability_sqft` (sq ft) |
| Leasing | `take_up_sqft`, `take_up_10y_avg_sqft`, `under_offer_sqft`, `active_demand_sqft` (sq ft); `take_up_vs_10y_avg` (%) |
| Pipeline | `under_construction_sqft`, `speculative_under_construction_sqft`, `completions_sqft`, `refurbishment_pipeline_sqft`, `pipeline_prelet_sqft`, `pipeline_speculative_sqft` (sq ft); `pre_let_share` (%) |
| Investment | `prime_yield` (%); `investment_volume_gbp` (GBP) |
| Macro | `bank_rate`, `sonia`, `gilt_10y_yield`, `cpih_yoy`, `cpi_yoy`, `gdp_growth_qoq`, `unemployment_rate`, `london_employment_rate` (%) |
| Occupier | `office_utilisation` (%) |

Tracked by default: prime rent, vacancy rate, take-up, under construction, prime yield,
Bank Rate, 10-year gilt yield.

**Protected metrics** (`catalog.PROTECTED_METRICS`) are referenced by code (report charts,
KPI tiles, macro data tools) and cannot be removed: `prime_rent`, `vacancy_rate`,
`take_up_sqft`, `take_up_10y_avg_sqft`, `pipeline_prelet_sqft`, `pipeline_speculative_sqft`
and the 8 macro series. A metric still listed by a skill must be removed from that skill first.

### Submarket catalogue (`catalog/submarkets.yaml`, `SubmarketDef`)
| Field | Type | Notes |
|---|---|---|
| `name` | str | Canonical name stored with every figure; never renamed |
| `kind` | `submarket` \| `macro` | Office submarket, or geography for economic series |
| `aliases` | list[str] | Other spellings; the validator maps them (case-insensitive) to `name`, e.g. Docklands → Canary Wharf |
| `description` | str | What area it covers |

Original entries: Central London, City, West End, Midtown, King's Cross, Southbank, Canary
Wharf, Shoreditch & Fringe, Paddington, Battersea & Nine Elms; macro: UK, London. Names and
aliases must be unique across all entries. **Protected:** Central London, UK, London.

### Editing safety (`versioned.py`)
Every catalogue (and skill) edit through the code keeps the previous file in a git-ignored
`.history/` folder (last 50 versions) and is refused with `ConflictError` if the file
changed since the editor loaded it (`Catalog.version` = content hash). Editing clears the
caches that embed the vocabulary (catalogue, skill registry, compiled skill agents).

**Period format** (`Metric.period`): quarters `2026-Q2`, half-years `2026-H1`, months
`2026-08`, years `2027`, days `2026-09-25`, weeks `week ending 2026-09-25`.
`periods.parse_period` turns a label into start and end dates plus a frequency (D/W/M/Q/H/Y).
Ordering uses the end date, never the text, because "2026-H1" sorts before "2026-Q1" as
text. Deltas and Dashboard lines only compare periods of the same frequency. Labels it
can't parse are kept and listed in tables, but left off time axes and out of deltas.

**Enums:** `SignalType` = `risk` | `opportunity`; `Severity` = `low` | `medium` | `high`.

## 3. Domain models (`schemas.py`)

### `Metric`: one numeric data point
| Field | Type | Required | Notes |
|---|---|---|---|
| `key` | str | ✓ | From the metric catalogue; normalised to snake_case |
| `submarket` | str | ✓ | From the submarket catalogue (aliases are mapped by the validator) |
| `value` | float | ✓ | Number only, no units |
| `unit` | str | ✓ | Should match the catalogue unit for `key` |
| `period` | str | ✓ | Period described, e.g. `2026-Q2` |
| `source` | str | ✓ | Publisher, e.g. `JLL`. Drives the like-for-like logic |
| `url` | str | – (`""`) | Link to the source. Missing → validator warning |
| `as_of` | date \| None | – | Publication date. Old → "stale" warning |
| `note` | str | – (`""`) | Definition caveats, e.g. "Grade A vacancy", "derived: …" |

### `Citation`
| Field | Type | Required |
|---|---|---|
| `title` | str | ✓ |
| `url` | str | ✓ (`""` if unknown) |
| `publisher` | str | – |
| `published` | date \| None | – |

### `Signal`: a risk or opportunity for a London office investor/developer
| Field | Type | Required | Notes |
|---|---|---|---|
| `type` | `SignalType` | ✓ | `risk` / `opportunity` |
| `severity` | `Severity` | ✓ | Sorts the risk/opportunity matrix |
| `title` | str | ✓ | Short label |
| `rationale` | str | ✓ | Evidence → implication |
| `submarket` | str | – | Default `Central London` |

### `SkillFinding`: the output contract of every skill
| Field | Type | Required | Notes |
|---|---|---|---|
| `skill` | str | ✓ | Always overwritten with the real skill name (not trusted from the LLM) |
| `headline` | str | ✓ | One-sentence takeaway |
| `summary` | str | ✓ | 2–5 sentence narrative |
| `metrics` | list[`Metric`] | – | |
| `insights` | list[str] | – | Bullet observations (deals, news items, …) |
| `signals` | list[`Signal`] | – | |
| `citations` | list[`Citation`] | – | |
| `confidence` | float 0–1 | – (0.5) | Self-assessed |
| `error` | str \| None | – | Set when the skill failed; the rest is then minimal |

### `ValidationIssue`: produced by the validator
| Field | Type | Notes |
|---|---|---|
| `level` | str | `warning` (kept, disclosed) or `error` (metric dropped) |
| `skill` | str | Which skill produced the problem |
| `message` | str | Human-readable explanation |
| `metric_key`, `submarket` | str \| None | What it refers to |

### `MetricDelta`: change versus an earlier period (computed, never stored)
| Field / property | Notes |
|---|---|
| `key`, `submarket`, `unit` | Identity of the metric |
| `previous`, `current` | Values |
| `previous_period`, `current_period` | Periods compared |
| `previous_source`, `current_source` | Publishers |
| `change` / `pct_change` | Absolute / relative change |
| `same_source` | False → labelled "different sources … not like-for-like" |
| `is_material` | ≥ 0.1pp for % metrics, ≥ 0.5% otherwise; immaterial moves are hidden |
| `describe()` | One-line text used in reports and prompts |

### `Incident`: a user-facing failure report (`errors.py`)
Created by `errors.incident_from_state` whenever any step of a chat turn or brief failed:
failed skills (`SkillFinding.error`) plus failed LLM steps (`AgentState.errors`). For
briefs this happens in `report_writer`, so the report, the CLI and the UI show the same
reference. It is stored in `findings_<run>.json` and, for chat turns, in
`turns.incident_json`.

| Field | Type | Notes |
|---|---|---|
| `id` | str | Reference users quote: `ERR-YYYYMMDD-HHMM-XXXX`. Also logged, so `grep` finds the details |
| `created_at` | datetime | |
| `category` | `ErrorCategory` | `code` (`access_denied`, `auth`, `credit`, `rate_limit`, `service`, `network`, `config`, `unknown`), `title`, `message`, `actions[]`, `retryable`. Chosen by ordered regex rules over the raw error text |
| `scope` | str | `total` (no usable result: red panel) or `partial` (answer may be incomplete: amber panel) |
| `affected` | list[str] | Failed steps, e.g. `office-rents`, `answer`, `synthesis` |
| `details` | list[str] | Raw `step: error` messages, shown only under "for engineers" |
| `thread_id`, `run_id`, `log_file` | str \| None | Where to look |

### `SkillSelection`: router output (chat mode)
`skills: list[str]` (unknown names are dropped), `reasoning: str`.

### `ExecutiveSynthesis`: brief summary
`title`, `executive_summary`, `key_takeaways: list[str]`, `risks: list[Signal]`,
`opportunities: list[Signal]`, `what_changed: list[str]`, `watch_list: list[str]`.

### `AnswerKey` / `KeyEntry`: the performance check's right answers (`benchmark/answer_key.py`)
`AnswerKey`: `report` (file in `style/reports/`), `title`, `publisher`, `period`, `built_at`,
`themes` (5-8 key messages, in the model's own words) and `entries`.

| `KeyEntry` field | Notes |
|---|---|
| `id` | Hash of key, submarket, period and source (stable across rebuilds) |
| `key`, `submarket`, `period`, `value`, `unit` | The figure, in catalogue terms |
| `source`, `citation` | Publisher of the figure; URL or reference the report gives |
| `confidence` | The AI's own confidence (0-1) |
| `status` | `pending` / `accepted` / `rejected`. Only `accepted` is scored |
| `in_document`, `catalogue_match`, `period_ok` | Signals computed in code (never taken from the model). `safe` = all true and confidence ≥ 0.8 |

### `RunRecord`: one performance-check run (`benchmark/store.py`)
`run_id`, `kind` (`figures` / `judge`), `report`, `created_at`, `period`, `hints`, `skills`,
`skipped_skills`, `brief_run_id`, `cost_usd` (estimate), `tokens_in`, `tokens_out`,
`duration_s`, `figure` (coverage, accuracy, same/other-source accuracy, mean abs % error,
unit correct, grounding), `entries` (expected vs found per figure), `citation` / `citations`
(cited-page check), `readability_brief` / `readability_reference`, `judgement` (rubric +
theme coverage) and `warnings`. Definitions: [EVALUATION.md](EVALUATION.md#metrics).

### `StyleProfile`: the learned house style (`style/profile.py`)
Saved as `style/profile.json` (plus a readable `profile.md`). Learned by
`cre-monitor style learn` from the examples in `style/reports/`; hand-editable.

| Field | Type | Notes |
|---|---|---|
| `name` | str | Shown in the report header badge and the prompts |
| `sources`, `learned_at`, `method` | list[str], str, str | Example file names, ISO timestamp, `llm` or `heuristic` |
| `voice`, `audience` | str | Tone and register, e.g. "first person plural ('we'), measured" |
| `layout` | list[`LayoutSection`] | Section order and headings: `{section, title, guidance}`, where `section` is one of `kpis`, `summary`, `what_changed`, `risks`, `charts`, `topics`, `watch_list`, `data_quality`, `sources` |
| `headline_style`, `paragraph_style`, `number_style` | str | E.g. "lead with the number", "short paragraphs", "£ psf, bp, Q2 2026" |
| `techniques`, `preferred_phrases`, `avoid` | list[str] | Signature techniques, phrasing to use, phrasing to avoid |
| `example_sentences` | list[str] | Short *paraphrased* illustrations of the style, never copied text |

`resolve_layout(profile)` turns `layout` into the `(section, heading)` list the report
templates loop over. Duplicates are ignored, and sections the profile omits get their
default headings and are placed before the reference sections, so no content is dropped.

## 4. Graph state (`graph/state.py`)

### `AgentState`: shared by all nodes
| Field | Set by | Notes |
|---|---|---|
| `mode` | caller | `brief` or `chat` |
| `messages` | caller, `chat_answer` | Reducer `add_messages`, so history accumulates per chat thread |
| `skills_override` | caller | Optional explicit skill list (`--skills`) |
| `context_refs` | caller (`ask(..., refs=)`) | Ids of earlier conversations referenced in this chat turn, cleaned and capped by `builder.resolve_refs`. Always set per turn, so references never carry over |
| `use_style` | caller (`run_brief(use_style=)`) | Brief only: apply the house style (default `True` when absent). Read by `synthesis` and `report_writer`; `REPORT_STYLE=0` overrides it |
| `reference_context` | `planner` | Context packs of `context_refs` (see §6). Read by the router and `chat_answer` only, **never** by the research skills |
| `run_id` | `planner` | `YYYYMMDDTHHMMSS-<6 hex>`. Keys the metrics rows and report files |
| `selected_skills`, `planner_reasoning` | `planner` | Shown in the UI |
| `findings` | `skill_runner` (append), `planner` / `validator` (replace) | Custom reducer `merge_findings`: plain lists append; `Replace([...])` overwrites (a sentinel first element, so it stays serialisable for checkpoints) |
| `validation_issues` | `validator` | list[`ValidationIssue`] |
| `deltas` | `persist` | list[`MetricDelta`] |
| `synthesis` | `synthesis` | `ExecutiveSynthesis` (brief only) |
| `report_paths` | `report_writer` | `{"html", "markdown", "json"}` → path |
| `answer` | `chat_answer` | Final chat text (never contains raw error text) |
| `errors` | `chat_answer`, `synthesis` | Raw `"step: error"` strings from failed LLM steps outside the skills. Reset by the planner each run |
| `incident` | `report_writer` (briefs, before rendering, so the report shows the reference) / `builder.ask` (chat) | `Incident` or `None`: the user-facing summary of all failures in the run, built by `errors.incident_from_state` |

### `SkillTask`: private input to one parallel skill run (via `Send`)
`skill_name`, `mode`, `question` (the user's question, or the standard brief instruction).

### `SkillAgentState`: inside one skill's sub-agent
`messages` (research transcript), `steps` (counted against `SKILL_MAX_STEPS`), `finding`.

## 5. Skill definition (`skills/<name>/SKILL.md`)

YAML frontmatter, validated by `SkillMetadata`, followed by a Markdown body: the
sub-agent's instructions.

| Field | Type | Default | Notes |
|---|---|---|---|
| `name` | str | required | Must equal the folder name |
| `description` | str (≥ 20 chars) | required | The only text the router sees |
| `tools` | list[str] | `[]` | Allow-list from the tool catalogue; `[]` = meta-skill |
| `metrics` | list[str] | `[]` | Keys the skill should return; must exist in the metric catalogue |
| `sanity_ranges` | dict[key → [min, max]] | `{}` | Validator drops values outside these |
| `preferred_domains` | list[str] | `[]` | Search hints |
| `model_tier` | str | `skill` | `router` / `skill` / `synthesis` |
| `in_brief` | bool | `true` | Include in the scheduled brief |
| `order` | int | `100` | Section order in the report |
| `keywords` | list[str] | `[]` | Fallback chat routing (whole-word match) |

Full authoring guide: [SKILLS.md](SKILLS.md).

## 6. Persistence: what is stored where

| Store | Written by | When | Contents |
|---|---|---|---|
| `data/metrics.sqlite` (table `metrics`) | `persist` node | Every brief **and** every chat turn, after validation | One append-only row per `Metric` (schema below). Only validated metrics are written: out-of-range values and failed skills are excluded. The first run seeds `fixtures/history.json` as `run_id='seed'` |
| `reports/<date>/brief_<run_id>.html`, `.md` | `report_writer` | Brief only | The rendered report |
| `reports/<date>/charts/<run_id>/*.png` | `report_writer` | Brief only, if `REPORT_PNG` | Static charts for the Markdown, one folder per run |
| `reports/<date>/findings_<run_id>.json` | `report_writer` | Brief only | Audit trail: `{run_id, synthesis, findings[], deltas[], issues[]}`, each item the JSON form of the models above |
| `data/checkpoints.sqlite` | LangGraph `SqliteSaver` | Chat only (`ask()`; `run_brief()` has no checkpointer) | Serialised `AgentState` per `thread_id` and step, including the message history. This is the **agent's memory** that makes a resumed conversation continue with context. Managed by LangGraph; don't edit by hand |
| `data/conversations.sqlite` (tables `conversations`, `turns`) | `ask()` → `ConversationStore.record_turn` | Every chat turn (UI and CLI) | The **conversation list** for the sidebar and `cre-monitor conversations`: title and timestamps per thread, plus each turn's question, answer, skills, issues and findings, so a reopened conversation can be redrawn with its charts (schema below) |
| `catalog/metrics.yaml`, `catalog/submarkets.yaml` | `catalog.py` (UI: Dashboard → Metrics / Submarkets) or by hand | On edit | The vocabularies (§2). Committed |
| `skills/<name>/SKILL.md` | `skills/editor.py` (UI: Skills tab) or by hand | On edit | The skills (§5). Committed |
| `skills/.history/<name>/`, `catalog/.history/` | `versioned.py` | Before each UI save | `<timestamp>__<file>` copies of the previous version, last 50 kept. Git-ignored |
| `skills/.trash/<name>__<timestamp>/` | `skills/editor.delete_skill` | On delete from the UI | Deleted skill folders, restorable. Git-ignored |
| `style/profile.json`, `style/profile.md` | `cre-monitor style learn` | On request | The house style (`StyleProfile`, above). Local by default (git-ignored); commit with `git add -f` to share one team style; read by `synthesis` and `report_writer` unless `REPORT_STYLE=0` |
| `style/library.json` | `style.set_roles` (UI library ticks) | On change | `{file: {"style": bool, "benchmark": bool}}` for the reports in `style/reports/`. Missing entry = style yes, benchmark no. Git-ignored |
| `style/benchmark/<file>.json` | `benchmark.answer_key.save_key` | Build / moderation | `AnswerKey` (below). Committable: numbers, links and short themes only. History in `style/benchmark/.history/` |
| `data/benchmarks/<run_id>.json` | `benchmark.store.save_run` | Each performance run / judgement | `RunRecord` (below) |
| `data/logs/<brief\|chat\|ui>_<date>.log` | `logs.setup_logging` (CLI and UI) | Every run | Run logs (INFO), including one `ERROR` record per `Incident`, searchable by its reference ID |

### `metrics` table schema (`store/metrics.py`)
| Column | Type | From |
|---|---|---|
| `run_id` | TEXT NOT NULL | `AgentState.run_id` (or `seed`) |
| `run_at` | TEXT NOT NULL | ISO timestamp of the run |
| `skill` | TEXT NOT NULL | `SkillFinding.skill` |
| `key`, `submarket` | TEXT NOT NULL | `Metric` |
| `value` | REAL NOT NULL | `Metric.value` |
| `unit` | TEXT | `Metric.unit` |
| `period` | TEXT NOT NULL | `Metric.period` |
| `source`, `url` | TEXT | `Metric` |
| `as_of` | TEXT | ISO date or NULL |
| `note` | TEXT | `Metric.note` |

Index: `(key, submarket, period)`. Rows are never updated, so history is auditable. Rows are
only ever removed when a user deletes a brief **with** its metrics
(`MetricsStore.delete_run`); the `seed` rows are protected.

Deleting a brief (`reporting/briefs.py: delete_brief`) removes:
* `brief_<run_id>.html` and `.md`;
* `findings_<run_id>.json`;
* `charts/<run_id>/`.

Pre-fix briefs share `charts/*.png`, which is removed with the last brief of the day; the
date folder is removed when it is empty. Run ids are validated against
`^\d{8}T\d{6}-[0-9a-f]{6}$`, so a delete can never touch paths outside `reports/`.
Reading rules:
* `series()` returns one row per (submarket, period, source), and the latest run wins;
* `deltas()` compares different periods only, prefers same-source history, and labels
  cross-source changes.

### Conversation tables (`store/conversations.py`)

Why two chat stores?
* The checkpointer holds the agent's memory in an opaque, LangGraph-managed format.
* The conversation store holds what the **UI** needs (titles, per-turn details) in simple
  documented tables.

They share the same `thread_id`. Deleting a conversation
(`builder.delete_conversation`) removes it from both.

`conversations`: one row per thread

| Column | Type | Notes |
|---|---|---|
| `thread_id` | TEXT PK | `new_thread_id()`: 12 hex chars. Also the `?thread=` URL value and the `--thread` CLI value |
| `title` | TEXT | First question, single line, max 60 chars; can be renamed |
| `created_at`, `updated_at` | TEXT | ISO timestamps; `updated_at` drives ordering and the Today/Yesterday/… grouping |

`turns`: one row per question/answer, PK `(thread_id, idx)`

| Column | Type | Notes |
|---|---|---|
| `thread_id`, `idx` | TEXT, INTEGER | `idx` is 0-based within the conversation |
| `created_at` | TEXT | ISO timestamp |
| `question`, `answer` | TEXT | As shown in the chat |
| `skills_json` | TEXT | JSON list of skills used |
| `reasoning` | TEXT | The router's reason for choosing them |
| `issues_json` | TEXT | JSON list of `ValidationIssue` |
| `findings_json` | TEXT | JSON list of `SkillFinding`. Lets the UI rebuild the turn's charts on reopen |
| `refs_json` | TEXT, default `'[]'` | JSON list of conversation ids referenced in this turn. Added later; older databases are upgraded automatically on open |
| `incident_json` | TEXT, nullable | JSON `Incident` if part of the turn failed. Lets a reopened conversation show the same error panel and reference. Added later; upgraded automatically |

In code these are read as `Conversation` (thread_id, title, created_at, updated_at,
turn_count) and `Turn` (idx, created_at, question, answer, skills, reasoning,
issues, findings, refs, incident) objects. `group_by_recency()` buckets conversations for the sidebar.

### Context pack (cross-conversation references)

`ConversationStore.context_pack(thread_id)` turns a stored conversation into background
text for another conversation. It is not stored; it is rebuilt each turn from the tables
above.

```
=== EARLIER CONVERSATION "<title>" (id <thread_id>, last active YYYY-MM-DD) ===
[YYYY-MM-DD] Q: <question>
A (excerpt): <first 400 chars of the answer…>
… (most recent 5 turns)
Key figures reported then (may be superseded by newer data):
- <submarket> <metric>: <value> <unit> (<period>, <source>; recorded YYYY-MM-DD)   (max 12)
```

Limits (`store/conversations.py`):
* `MAX_REFS = 3` conversations per question;
* `PACK_MAX_TURNS = 5`;
* `PACK_ANSWER_CHARS = 400`;
* `PACK_MAX_FIGURES = 12`;
* `PACK_MAX_CHARS = 4000` per conversation.

The dates are there so the model can tell when an earlier figure may be out of date.

### Notes

Narrative content (headlines, insights, signals) is **not** in the metrics table. It lives
in the findings JSON, the reports, and, for chat turns, `turns.findings_json`.
`data/` and `reports/` are git-ignored. To reset, delete `data/`: metrics are re-seeded on
the next run, but saved conversations are lost.

### Merge (`store/merge.py`)
`merge_installation()` merges another installation's SQLite databases and report files
into this one. It is SQLite-specific, unlike the export.

| Database | Identity used for matching | Rule |
|---|---|---|
| `metrics` | The whole row (all 12 columns) | Insert rows not already present; source `seed` rows are skipped if the target has seed rows |
| `conversations` / `turns` | `thread_id`; turns by `(created_at, question)` | added / skipped (source turns ⊆ target) / extended (target is a prefix of source: append, re-index) / renamed (`<id>-<4 hex>`, with `refs_json` and the incident `thread_id` remapped) |
| LangGraph `checkpoints`, `writes` | `(thread_id, checkpoint_ns, checkpoint_id[, task_id, idx])` | For added/extended/renamed threads (and memory-only threads absent from the target): `INSERT OR IGNORE`, with the thread id rewritten for renames. Any table with a `thread_id` column is handled, so new LangGraph tables are covered |

The source is opened read-only (`mode=ro`). A real merge is **all-or-nothing** and runs in
phases:

1. **Rehearse** the full merge on in-memory copies of the target (this is also the dry
   run).
2. **Lock** each target with `BEGIN IMMEDIATE` (5 s timeout). Failing to get the lock →
   `MergeError(restored=False)`.
3. **Back up** via the SQLite backup API.
4. **Apply and commit** each database, then copy brief files.
5. **On failure after step 3**, restore every database from the backup, delete
   databases the merge created, and remove copied brief files → `MergeError(restored=True)`.

A single cross-file transaction (ATTACH) is not used: LangGraph keeps `checkpoints.sqlite`
in WAL mode, where SQLite does not guarantee atomic commits across files. Older source
schemas (e.g. without `refs_json` or `incident_json`) are read with defaults.

### Export (`export.py`)
`export_data()` reads **through the store classes** (`MetricsStore.frame`,
`ConversationStore.list/turns`, `list_briefs`), never the SQLite files directly, so it is
unaffected by a future storage change. Layout and file formats:
[USAGE.md → Exporting data](USAGE.md#exporting-data). `conversations.json` is a list of
`{thread_id, title, created_at, updated_at, turns: [{idx, created_at, question, answer,
skills, reasoning, references, incident, data_quality_issues, findings}]}`, using the JSON
form of the models in §3.

## 7. Fixture formats (`fixtures/`)

| File | Shape | Used by |
|---|---|---|
| `findings/<skill>.json` | One `SkillFinding` | Demo mode, tests |
| `history.json` | list[`Metric`] | Seeds the metrics store |
| `macro_series.json` | `{name: {name, label, source, url, observations: [{period, value}]}}` | `boe_series` / `ons_series` offline |
| `search_results.json` | list[`{title, url, snippet, published, source}`] | `web_search` offline |
| `news.json` | list[`{title, url, published, feed, summary}`] | `rss_news` offline |
| `documents/index.json` + `*.txt` | `{url: filename}` + text summaries | `fetch_document` offline |

Provenance of every figure: [fixtures/README.md](../fixtures/README.md).
