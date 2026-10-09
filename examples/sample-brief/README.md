# Sample brief: a full live run (redacted)

**[Open the brief (Markdown, with charts)](brief_20261008T070945-5e5fe0.md)** · HTML version:
[`brief_20261008T070945-5e5fe0.html`](brief_20261008T070945-5e5fe0.html) (download and open in a
browser for interactive charts) · structured data:
[`findings_20261008T070945-5e5fe0.json`](findings_20261008T070945-5e5fe0.json)

## What this is

A real **London Office Market Brief** produced by the agent in **live mode** (Claude + live web
search and public APIs) on **8 October 2026, 07:09** in a GitHub Codespace (run
`20261008T070945-5e5fe0`), and merged into this installation with `cre-monitor merge`.

* All **8 research skills** ran successfully: rents, vacancy, take-up, supply pipeline,
  submarkets, macro, occupier demand, news.
* The latest broker data available then was **Q2 2026**; Q3 reports were not yet published.
* Sources kept here: Avison Young, JLL, Savills, Cushman & Wakefield, Colliers, Bank of England,
  ONS / Nomis, Property Week, Financial Times (headlines) and others - each figure links to its
  source.

## What was removed, and why

The original run also used **Knight Frank** (whose terms prohibit reproduction and use on AI
platforms) and **CoStar**-licensed data. Before committing, that content was removed with
[`scripts/publish_sample_brief.py`](../../scripts/publish_sample_brief.py), which re-renders the brief
from its findings (no new research, no LLM call):

| Removed | Count |
|---|---|
| Figures from restricted sources | 51 of 100 |
| Their citations | 8 |
| Sentences / bullets that named a restricted source or quoted a removed figure | 27 / 44 |
| Risk & opportunity signals that did so | 20 |
| "What changed" comparisons and validator notes involving them | 3 / 6 |

The rules are deliberately conservative, so some sentences that merely *coincide* with a removed
figure were dropped too. Removed headlines and summaries are marked "(... removed ...)". Charts
were rebuilt without restricted history - e.g. prime rents show JLL's figures only.

## Reading it

* The header and KPI tiles show the latest figure per indicator with its period and source.
* Brokers define metrics differently: the brief keeps their figures side by side and labels
  cross-source comparisons ("not like-for-like") instead of averaging them.
* This is a PoC output for evaluating the agent - not investment advice. To measure its accuracy
  systematically, use the performance check ([docs/EVALUATION.md](../../docs/EVALUATION.md)).

To publish another run the same way:
`python scripts/publish_sample_brief.py reports/<date>/findings_<run_id>.json examples/<name>`
- then review the output before committing.
