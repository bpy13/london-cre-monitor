---
name: macro-economy
description: >-
  Macroeconomic drivers of London real estate - Bank Rate and the rate outlook, gilt yields,
  inflation (CPIH/CPI), GDP growth, UK unemployment and London employment - from official
  Bank of England and ONS data. Use for questions on interest rates, financing costs,
  inflation, the economy, employment or how macro affects pricing and demand.
tools: [boe_series, ons_series, rss_news, web_search]
metrics: [bank_rate, sonia, gilt_10y_yield, cpih_yoy, cpi_yoy, gdp_growth_qoq, unemployment_rate, london_employment_rate]
sanity_ranges:
  bank_rate: [0, 15]
  sonia: [0, 15]
  gilt_10y_yield: [0, 15]
  cpih_yoy: [-5, 25]
  cpi_yoy: [-5, 25]
  gdp_growth_qoq: [-25, 25]
  unemployment_rate: [1, 20]
  london_employment_rate: [50, 90]
preferred_domains:
  - bankofengland.co.uk
  - ons.gov.uk
  - obr.uk
  - ft.com
model_tier: skill
in_brief: true
order: 60
keywords: [interest rate, interest rates, bank rate, base rate, boe, bank of england, gilt, yield curve, inflation, cpi, cpih, gdp, economy, recession, unemployment, employment, jobs, macro, financing, mpc]
---

# Macro-economy

## Goal
Provide the macro backdrop that drives London office **pricing** (via rates/yields) and
**demand** (via employment and growth), using official sources.

## Method
1. **Always** pull official data first (these tools are free, keyless, authoritative):
   - `boe_series("bank_rate")`, `boe_series("gilt_10y_yield")`, `boe_series("sonia")`
   - `ons_series("cpih_yoy")`, `ons_series("gdp_growth_qoq")`, `ons_series("unemployment_rate")`,
     `ons_series("london_employment_rate")`
2. Use `rss_news(feed="bank_of_england", query="Monetary Policy")` for the latest MPC
   decision/minutes, and `rss_news(feed="ons_releases", query="inflation labour GDP")`
   for upcoming data releases (feed into the watch list).
3. Use `web_search` only for the market-implied rate path / forecasts (e.g.
   `"Bank of England rate expectations October 2026"`) and cite it as market commentary.

## Recording metrics
- Use submarket **"UK"** for national series and **"London"** for London-only series.
- Period format: daily BoE series -> use the latest date's month (`"2026-10"`);
  monthly ONS -> `"2026-08"`; quarterly GDP -> `"2026-Q2"`; APS London employment ->
  the end month of the 12-month window if clear (e.g. `"2026-03"`).
- Source: "Bank of England", "ONS", or "ONS (Nomis APS)". URL as returned by the tool.

## Interpreting for CRE
- **Gilt yields** are the risk-free benchmark for property yields: a rising 10-year gilt
  squeezes the yield spread and puts upward pressure on prime office yields (downward
  pressure on values) unless rental growth compensates. Note the prime yield-gilt spread
  if prime yields are known.
- **Bank Rate / SONIA** drive debt costs and refinancing risk for leveraged owners -
  distressed sales can create acquisition opportunities.
- **Inflation** feeds construction costs (pipeline viability) and indexation in leases.
- **Employment** in London (especially office-based sectors: finance, professional
  services, tech) drives medium-term space demand.

## Output guidance
- One metric per series (latest value). Add the direction over the last 6-12 months in insights.
- Signals: e.g. "Higher-for-longer gilt yields cap capital value recovery" (risk) or
  "Rate cuts lower financing costs, reviving investment volumes" (opportunity).
