---
name: occupier-demand
description: >-
  Structural occupier demand drivers - flight-to-quality, ESG and sustainability
  requirements (EPC ratings, MEES regulations, BREEAM/NABERS, net zero), hybrid working
  and office utilisation, amenity and location preferences. Use for questions on why and
  what kind of space occupiers want, ESG/green buildings, stranded assets or return-to-office.
tools: [web_search, fetch_document, rss_news]
metrics: [office_utilisation, grade_a_share_of_availability]
sanity_ranges:
  office_utilisation: [0, 100]
preferred_domains:
  - knightfrank.co.uk
  - cbre.co.uk
  - jll.co.uk
  - savills.co.uk
  - bpf.org.uk
  - ukgbc.org
  - gov.uk
  - remit.com
model_tier: skill
in_brief: true
order: 70
keywords: [esg, sustainability, sustainable, green, epc, mees, breeam, nabers, net zero, carbon, flight to quality, flight-to-quality, hybrid, work from home, wfh, return to office, utilisation, occupancy, amenity, stranded]
---

# Occupier demand drivers

## Goal
Explain the *qualitative* forces shaping what occupiers lease, and quantify them where data
exists - this is what separates "how much space" from "what kind of space wins".

## Themes to cover
1. **Flight-to-quality**: share of take-up in new/Grade A or best-in-class buildings;
   rent premium for top-quality, highly amenitised, well-connected buildings.
2. **ESG / sustainability**:
   - **MEES** (Minimum Energy Efficiency Standards) for commercial lettings in England &
     Wales: currently EPC **E** minimum; the government's proposed trajectory is EPC **C**
     by 2027 and **B** by 2030. Always check the **latest** government position via
     search - consultation outcomes may have changed dates/levels - and say so.
   - Corporate net-zero targets drive demand for BREEAM Outstanding/Excellent, NABERS UK,
     all-electric buildings; "green premium" vs "brown discount".
   - Embodied carbon: planning policy (e.g. City of London "retrofit first") favouring refurbishment.
3. **Hybrid working**: office utilisation/attendance (e.g. Remit Consulting, Freespace,
   broker occupier surveys), mandated office days at large employers, space-per-worker trends,
   right-sizing on lease events vs upsizing into quality.
4. **Amenity & location**: proximity to Elizabeth line / major hubs, hospitality-led services.

## Method
1. Search, e.g. `"London office flight to quality 2026 Grade A share of take-up"`,
   `"MEES EPC B 2030 commercial update 2026"`, `"London office occupancy utilisation 2026"`,
   `"return to office mandate London 2026"`.
2. Read one substantive source per theme (focus keywords per theme).
3. Use `rss_news` for recent ESG regulation news and corporate office mandates.

## Interpreting for Nan Fung
- ESG non-compliant (EPC D-G) stock faces **stranding risk** -> capex needs, value discount;
  also an **acquisition-and-retrofit opportunity** where pricing reflects it.
- Strong flight-to-quality supports prime development/refurbishment economics.
- Hybrid working reduces average space per company but raises quality expectations.

## Output guidance
- Metrics only where a credible number exists (`office_utilisation` %, Grade A share).
- Most value here is in `insights` and `signals` - be specific and cite sources.
