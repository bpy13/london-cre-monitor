---
name: office-rents
description: >-
  Prime and Grade A office rents across central London submarkets - headline rents
  (GBP psf pa), rental growth, rent-free incentives and net effective rents. Use for any
  question about rent levels, rental growth, record rents or incentives.
tools: [web_search, fetch_document, metrics_history]
metrics: [prime_rent, grade_a_rent, prime_rent_growth_yoy, rent_free_months]
sanity_ranges:
  prime_rent: [30, 400]
  grade_a_rent: [25, 300]
  rent_free_months: [0, 48]
  prime_rent_growth_yoy: [-40, 60]
preferred_domains:
  - knightfrank.co.uk
  - cbre.co.uk
  - jll.co.uk
  - savills.co.uk
  - realestate.bnpparibas.co.uk
  - cushmanwakefield.com
  - avisonyoung.co.uk
model_tier: skill
in_brief: true
order: 10
keywords: [rent, rents, rental, psf, per sq ft, incentive, rent-free, rent free, net effective]
---

# Office rents

## Goal
Establish the current **prime** and **Grade A** headline rents for central London and
its main submarkets, how they are trending, and what incentives landlords are offering.

## Definitions (be precise - brokers differ)
- **Prime rent**: the top rent achievable for a hypothetical best-in-class unit (best
  building, best floor, typical size) - *not* the single record deal. Reported in
  **GBP per sq ft per annum** (GBP psf pa).
- **Grade A rent / average Grade A**: typical rent for new or comprehensively refurbished
  space. Lower than prime; some brokers call it "Grade A average" or "new build".
- **Rent-free**: months of rent-free on a typical 10-year term (headline vs net effective
  gap). Rising rent-free with flat headline rents = weakening market.
- **Net effective rent**: headline rent after incentives. Mention when available.
- Record/trophy deals (e.g. GBP 200+ psf in Mayfair/St James's) are *insights*, not the
  prime rent metric - add them to `insights`, not `metrics`, unless the broker states
  prime has moved.

## Method
1. Search for the latest quarterly central London office reports, e.g.
   `"Knight Frank London office market Q3 2026 prime rent"`,
   `"CBRE central London office rents Q3 2026"`, `"JLL London office prime rents"`.
2. Read at least one primary broker source with `fetch_document` (focus: "prime rent,
   rent free, Grade A"). Use a second broker to cross-check West End and City.
3. Call `metrics_history` for `prime_rent` to compare against what we recorded before
   and describe the trend (e.g. "fourth consecutive quarter of growth").
4. Cover at minimum: **West End (Mayfair/St James's), City, Canary Wharf, Midtown,
   King's Cross**, plus Southbank / Shoreditch & Fringe if available.

## Interpreting
- Prime rental growth with supply shortage of best space = classic **flight-to-quality**
  signal; growth concentrated in top buildings while secondary stagnates = **two-tier market**.
- Signals for a landlord/developer: rising prime rents and falling incentives are
  opportunities for prime development/refurbishment; widening prime-secondary gap is a
  risk for older stock (stranding).

## Output guidance
- One `prime_rent` metric per submarket per source, with `period` = quarter (e.g. 2026-Q3).
- `prime_rent_growth_yoy` in % where the source states it.
- `rent_free_months` for Central London or per submarket.
