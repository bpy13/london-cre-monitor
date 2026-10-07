---
name: leasing-take-up
description: >-
  Office leasing activity - quarterly take-up volumes vs long-term averages, space under
  offer, active requirements, largest lettings and which business sectors are taking space.
  Use for questions about leasing, lettings, take-up, demand volumes or major deals.
tools: [web_search, fetch_document, rss_news, metrics_history]
metrics: [take_up_sqft, take_up_vs_10y_avg, take_up_10y_avg_sqft, under_offer_sqft, active_demand_sqft]
sanity_ranges:
  take_up_sqft: [50000, 6000000]
  take_up_10y_avg_sqft: [1000000, 5000000]
  take_up_vs_10y_avg: [-80, 150]
  under_offer_sqft: [100000, 8000000]
  active_demand_sqft: [1000000, 30000000]
preferred_domains:
  - knightfrank.co.uk
  - cbre.co.uk
  - jll.co.uk
  - savills.co.uk
  - estatesgazette.co.uk
  - realestate.bnpparibas.co.uk
model_tier: skill
in_brief: true
order: 30
keywords: [take-up, take up, leasing, letting, lettings, deal, deals, under offer, requirement, demand volume, signed]
---

# Leasing & take-up

## Goal
Quantify occupier leasing activity and characterise who is taking space and where.

## Definitions
- **Take-up**: space let (signed leases) in the period, sq ft. Brokers differ on whether
  pre-lets, renewals and lease regears are included - note it.
- **10-year average**: compare the latest quarter with the quarterly 10-year average
  (record as `take_up_10y_avg_sqft`) and the % difference (`take_up_vs_10y_avg`).
- **Under offer**: space where heads of terms are agreed but not yet signed - a lead
  indicator for next quarter's take-up.
- **Active demand / requirements**: total sq ft of occupiers actively searching.

## Method
1. Search: `"central London office take-up Q3 2026"`, `"London office leasing Q3 2026 under offer"`.
2. Read one broker report in full (focus: "take-up, under offer, active demand, sector").
3. Use `rss_news` (feed "google_news", query like "London office letting pre-let") to
   catch the largest recent deals; list the top 3-5 deals in `insights` with occupier,
   building, size and submarket.
4. Use `metrics_history` for `take_up_sqft` to compare against previous quarters.
5. Record sector mix (financial services, tech/media, professional services, etc.) in insights.

## Interpreting
- Take-up above average with under-offer rising = strengthening demand.
- High share of deals in new/Grade A space = flight-to-quality (link to occupier-demand skill).
- Large pre-lets indicate occupiers securing scarce future supply - opportunity for
  developments with near-term delivery.

## Output guidance
- `take_up_sqft` for Central London (required) and submarkets where available; period = quarter.
- `under_offer_sqft` and `active_demand_sqft` for Central London.
