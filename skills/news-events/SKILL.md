---
name: news-events
description: >-
  Emerging news and events affecting the London office sector in the last ~30 days -
  major deals and relocations, investment transactions, planning decisions, distress and
  refinancing, policy/regulation changes, transport and macro shocks. Use for "what's new",
  "latest news", recent events or early-warning questions.
tools: [rss_news, web_search, fetch_document]
metrics: [prime_yield, investment_volume_gbp]
sanity_ranges:
  prime_yield: [2, 12]
  investment_volume_gbp: [10000000, 50000000000]
preferred_domains:
  - estatesgazette.co.uk
  - propertyweek.com
  - react-news.com
  - ft.com
  - cityam.com
  - bloomberg.com
model_tier: skill
in_brief: true
order: 80
keywords: [news, latest, recent, this week, this month, event, events, announced, relocation, relocating, acquisition, sale, sold, distress, administration, refinancing, planning approval, policy]
---

# News & events

## Goal
Surface the **recent events (last ~30 days)** most likely to matter for a London office
investor/developer, and flag early warnings.

## Method
1. Scan headlines broadly:
   - `rss_news(feed="google_news", query="London office market")`
   - `rss_news(feed="google_news", query="City of London office letting OR acquisition")`
   - `rss_news(feed="estates_gazette", query="office London")`
   - `rss_news(feed="google_news", query="London office distress refinancing administration")`
2. Pick the 5-8 most material items. For the top 2-3, open the article with
   `fetch_document` to confirm the facts (size, price, parties, submarket).
3. Use `web_search` to fill gaps, e.g. latest quarterly **investment volume** and
   **prime yield** for central London (`"central London office investment volume Q3 2026"`).

## What counts as material (prioritise)
- Lettings > 100,000 sq ft, HQ relocations, pre-lets of schemes under construction.
- Investment deals > GBP 100m, notable pricing (yield) evidence, overseas buyers/sellers.
- Distress: receiverships, forced sales, loan defaults, landlord administrations.
- Policy: MEES/EPC changes, planning reform, business rates, Budget measures, City/
  Westminster planning decisions.
- Transport/infrastructure and big corporate return-to-office mandates.
- Anything specifically about **our own portfolio** or peers'/competitor schemes.

## Output guidance
- `insights`: each item as "[date] What happened - why it matters (submarket)" with the
  source name. Keep to one line each.
- `signals`: flag early warnings (risk) and openings (opportunity), e.g. distressed sales
  creating acquisition opportunities.
- Metrics only for investment volume (`investment_volume_gbp`, Central London, quarter)
  and `prime_yield` (by submarket) when a credible source gives them.
- `citations`: every news item cited.
