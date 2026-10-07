---
name: vacancy-availability
description: >-
  Office vacancy and availability rates and volumes for central London and submarkets,
  split by new/Grade A vs second-hand space. Use for questions about vacancy, availability,
  empty space, supply of space to let, or Grade A scarcity.
tools: [web_search, fetch_document, metrics_history]
metrics: [vacancy_rate, availability_sqft, grade_a_share_of_availability, new_build_vacancy_rate]
sanity_ranges:
  vacancy_rate: [0, 35]
  new_build_vacancy_rate: [0, 30]
  availability_sqft: [100000, 60000000]
  grade_a_share_of_availability: [0, 100]
preferred_domains:
  - knightfrank.co.uk
  - cbre.co.uk
  - jll.co.uk
  - savills.co.uk
  - realestate.bnpparibas.co.uk
  - avisonyoung.co.uk
model_tier: skill
in_brief: true
order: 20
keywords: [vacancy, vacant, availability, available, empty, void, supply of space, grade a scarcity]
---

# Vacancy & availability

## Goal
Measure how much office space is on the market, where, and of what quality.

## Definitions (critical - figures are NOT comparable across brokers)
- **Vacancy rate**: vacant space as % of total stock. Some brokers include space
  available within 6-12 months, some include under-offer space - record this in `note`.
- **Availability**: total space actively marketed (vacant + soon-to-be-vacant), in sq ft.
  Availability rate > vacancy rate typically.
- **New build / Grade A vacancy**: vacancy within new or refurbished space only. Very low
  new-build vacancy alongside higher overall vacancy = shortage of quality space.
- Central London ~ 230-260m sq ft of stock; the City ~ 90m+, West End ~ 70m+,
  Canary Wharf/Docklands ~ 20m+ (approximate - for sanity checks only).

## Method
1. Search latest-quarter broker reports for vacancy/availability, e.g.
   `"central London office vacancy rate Q3 2026"`, `"City of London availability Q3 2026"`.
2. Read one primary source in full (focus: "vacancy, availability, new build, second-hand").
3. Get submarket splits: **City, West End, Canary Wharf, Midtown, King's Cross, Southbank,
   Shoreditch & Fringe** where provided.
4. Use `metrics_history` for `vacancy_rate` to describe direction and compare with the
   long-run (~5-year) average if the source gives one.

## Interpreting
- Falling vacancy + low new-build vacancy -> rental growth pressure for prime; supports
  development/refurbishment opportunities.
- Rising second-hand availability (often Canary Wharf, older City stock) -> risk to
  secondary values; potential repositioning/conversion opportunities.
- Tenant-controlled (sublease) space rising is an early warning sign of occupier retrenchment.

## Output guidance
- `vacancy_rate` per submarket in %, with `note` describing the broker's definition.
- `grade_a_share_of_availability` in % if stated.
