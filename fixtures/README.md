# Fixtures (offline data)

Used when `CRE_OFFLINE=1` (tools) and `CRE_DEMO_MODE=1` (canned skill findings), and by the
test suite. **All figures are real, publicly published data with source URLs**, collected in
October 2026. Nothing is invented.

| File | Contents | Provenance |
|---|---|---|
| `findings/<skill>.json` | One complete `SkillFinding` per research skill | Avison Young Q2 2026, JLL Q2 2026, BNP Paribas RE Q1 2026, Carter Jonas Q2 2026, Savills (via K2 Space), CoStar News, London Construction Magazine, Bank of England, ONS |
| `history.json` | Seed for the metrics store: earlier-quarter CRE points + monthly macro history | Avison Young Q3 2025 / Q2 2026, BNP Paribas RE Q1 2026; BoE IADB and ONS series (fetched live) |
| `macro_series.json` | Canned responses for `boe_series` / `ons_series` | Fetched live from BoE IADB, ONS, Nomis on 2026-10-07 |
| `search_results.json` | Canned `web_search` hits | Titles/URLs of the sources above, with short paraphrased snippets |
| `documents/*.txt` | Canned `fetch_document` extracts | Short **summaries in our own words**, not copies |
| `news.json` | Canned `rss_news` headlines | Real articles/pages listed above |

Notes:
* A few values are marked `derived` in their `note` field, e.g. the 10-year average
  take-up (2.45m sq ft), which is derived from Avison Young's statement that 2.6m was "6%
  above the 10-year average".
* Brokers' vacancy definitions differ (Avison Young 6.3% vs JLL 8.6% for Q2 2026). The
  fixture deliberately keeps both, which also exercises the validator's conflict check.
* Some broker publications (e.g. Knight Frank) prohibit reproduction or use of their data
  on AI platforms. Their figures are therefore **not** included here. Check licensing
  before adding any broker's data, and before using broker documents with the live agent
  in production.

Regenerating the macro fixtures: fetch the series with the `boe_series` / `ons_series`
tools in online mode, and keep the latest observation out of `history.json` (it belongs in
the current findings, so that deltas are computed).
