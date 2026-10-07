# Skill authoring guide

A **skill** packages one research area: what to look for, how to find it, how to
interpret it, and what structured output to return. Skills live in
`skills/<name>/SKILL.md` and are loaded automatically by `skills/registry.py`.

## Anatomy

```markdown
---
name: office-rents                 # REQUIRED - must equal the folder name
description: >-                    # REQUIRED (>= 20 chars) - the ONLY text the router sees.
  Prime and Grade A office rents ...  Say what it covers AND when to use it.
tools: [web_search, fetch_document, metrics_history]   # allow-list; [] = meta-skill
metrics: [prime_rent, grade_a_rent]                    # keys it should return (schemas.METRIC_KEYS)
sanity_ranges:                                         # validator drops values outside these
  prime_rent: [30, 400]
preferred_domains: [knightfrank.co.uk, cbre.co.uk]     # hints for search queries
model_tier: skill                  # router | skill | synthesis
in_brief: true                     # include in the scheduled full brief
order: 10                          # section order in the report
keywords: [rent, psf, incentive]   # fallback routing when no LLM router is available
---

# Markdown body = the sub-agent's expert instructions
## Goal / Definitions / Method / Interpreting / Output guidance
```

The body is appended to the shared research rules in
`graph/nodes/skill_runner.py::COMMON_RULES`. Those rules cover always citing sources,
never inventing figures, normalising submarket names, and using the controlled metric keys.

## Writing good instructions
* **Define terms precisely.** Brokers use "vacancy", "availability" and "take-up"
  differently. Tell the agent to record the definition in `Metric.note`.
* **Give concrete query templates** (with the period), e.g.
  `"Knight Frank London office take-up Q3 2026"`.
* **Say which sources are primary.** Name the brokers or official bodies to prefer, and
  ask for verification with `fetch_document`.
* **Explain the investment lens.** What makes something a *risk* or an *opportunity* for
  a London office landlord/developer?
* **Specify output.** Which metrics, which submarkets, and which period format.
* Keep it under roughly 150 lines. Long prompts cost tokens on every run.

## Available tools
| Tool | Purpose |
|---|---|
| `web_search(query, domains?, recency_days?)` | Web search (Tavily → Google News fallback) |
| `fetch_document(url, focus?)` | Full text of a page/PDF, optionally filtered to keyword paragraphs |
| `rss_news(feed, query, limit)` | Headlines: `google_news`, `estates_gazette`, `bank_of_england`, `ons_releases`, `all` |
| `boe_series(name, months)` | `bank_rate`, `sonia`, `gilt_10y_yield` |
| `ons_series(name)` | `cpih_yoy`, `cpi_yoy`, `unemployment_rate`, `gdp_growth_qoq`, `london_employment_rate` |
| `metrics_history(key, submarket?)` | Values we recorded in earlier runs |

## Adding a skill: checklist
1. `mkdir skills/<name>` and write `SKILL.md` (copy an existing one as a template).
2. Any new metric keys go in `src/cre_monitor/schemas.py::METRIC_KEYS` (with the unit).
3. Add `fixtures/findings/<name>.json`: a realistic, **cited** `SkillFinding` used in
   demo mode and tests.
4. Run `cre-monitor skills` to confirm it loads (invalid skills are listed in red).
5. Run `pytest`. `tests/test_skills.py` validates every skill, and the demo graph test
   runs it. Update `EXPECTED_RESEARCH_SKILLS` in that test.
6. Optional: add a chart in `reporting/charts.py` if the skill introduces a key metric.

Ideas for future skills: `investment-market` (volumes, yields, buyer mix),
`life-sciences-space`, `flex-workspace`, `competitor-schemes` (tracking specific
developments), `planning-tracker` (London Datastore planning applications).

## Refreshing fixtures
Fixtures hold **real, cited** figures so that demos are credible. When new quarterly
reports land:
1. Update `fixtures/findings/*.json` with the new figures, sources and URLs.
2. Append the previous quarter's values to `fixtures/history.json`.
3. Update `fixtures/search_results.json`, `fixtures/documents/*` and `fixtures/news.json`
   if the fake-LLM tests rely on them.
4. Run `pytest`.
