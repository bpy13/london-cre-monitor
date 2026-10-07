---
name: supply-pipeline
description: >-
  Development supply pipeline - space under construction, speculative vs pre-let, expected
  completions by year, major refurbishments, and planning/construction starts. Use for
  questions about new supply, developments, refurbishments, pre-lets or future competition.
tools: [web_search, fetch_document, rss_news, metrics_history]
metrics:
  - under_construction_sqft
  - speculative_under_construction_sqft
  - pre_let_share
  - completions_sqft
  - refurbishment_pipeline_sqft
  - pipeline_prelet_sqft
  - pipeline_speculative_sqft
sanity_ranges:
  under_construction_sqft: [1000000, 40000000]
  speculative_under_construction_sqft: [0, 30000000]
  pre_let_share: [0, 100]
  completions_sqft: [0, 15000000]
  refurbishment_pipeline_sqft: [0, 20000000]
  pipeline_prelet_sqft: [0, 15000000]
  pipeline_speculative_sqft: [0, 15000000]
preferred_domains:
  - knightfrank.co.uk
  - cbre.co.uk
  - jll.co.uk
  - savills.co.uk
  - estatesgazette.co.uk
  - cityoflondon.gov.uk
  - deloitte.com
model_tier: skill
in_brief: true
order: 40
keywords: [pipeline, development, developments, construction, completion, completions, refurb, refurbishment, pre-let, prelet, speculative, new supply, planning]
---

# Supply pipeline

## Goal
Understand how much new and refurbished office space will be delivered, when, where,
and how much is already committed (pre-let) - i.e. the future competitive supply.

## Definitions
- **Under construction**: schemes on site. Split **speculative** (no tenant committed)
  vs **pre-let** (committed). `pre_let_share` = pre-let / total under construction, %.
- **Completions by year**: expected delivery by calendar year. Record the split as
  `pipeline_prelet_sqft` and `pipeline_speculative_sqft` with `period` = the year
  (e.g. "2027"), submarket "Central London". These feed the pipeline chart.
- **Refurbishment pipeline**: major refurbishments ("retrofit-first") - increasingly a large
  share of new Grade A supply due to cost of new build and embodied-carbon policy.
- Useful sources: broker development reports, Deloitte London Office Crane Survey,
  City of London development pipeline publications, Estates Gazette development news.

## Method
1. Search: `"London office development pipeline 2026 under construction speculative"`,
   `"London office crane survey 2026"`, `"City of London office pipeline 2027 2028"`.
2. Read at least one primary source (focus: "under construction, speculative, pre-let,
   completions, refurbishment").
3. Use `rss_news` for recent construction starts, planning consents or delayed schemes.
4. Note **delays/cancellations** (build-cost inflation, financing) - they tighten future supply.

## Interpreting
- Low speculative pipeline vs strong Grade A demand -> supply gap for 2027-2029 =
  opportunity for well-located schemes/refurbishments delivering in that window.
- Concentrated speculative completions in one submarket and year -> letting risk/competition.
- Slowing construction starts are a forward signal of future rental growth.

## Output guidance
- `under_construction_sqft`, `speculative_under_construction_sqft`, `pre_let_share` for
  Central London (and City/West End if available).
- Pipeline split by completion year (3-4 years ahead) for the chart.
