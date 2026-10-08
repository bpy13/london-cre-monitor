# Evaluating the agent: the performance check

The test suite ([TESTING.md](TESTING.md)) proves the **code** behaves, using fakes and
fixtures. The performance check measures whether the agent's **research is right**, using
reports your team trusts as the reference.

- [How it works](#how-it-works)
- [The answer key and moderation](#the-answer-key-and-moderation)
- [Metrics](#metrics)
- [Cost](#cost)
- [Reading the scorecard](#reading-the-scorecard)
- [Limits](#limits)
- [Code map](#code-map)

## How it works

```
reference report (style/reports/, ticked "Benchmark")
   │ 1. Claude extracts the figures it states + its key themes      → answer key (style/benchmark/<file>.json)
   │ 2. analyst moderates with the signals, accepts the right ones
   ▼
figure run: only the skills that collect the accepted figures, asked for THAT period
   │ (optionally given the report's publisher/citations as leads)
   ▼
production validator → scoring (coverage, accuracy, grounding) → citation check → cost → data/benchmarks/<run>.json

brief judgement: an existing brief vs the reference → readability + citation check (free) + Claude rubric
```

Run it from the UI (**📚 Reference reports → 🎯 Performance check**) or the CLI:

```bash
cre-monitor --live bench key bnp_q1_2026.html --accept-safe   # build the answer key (then moderate in the UI)
cre-monitor --live bench run bnp_q1_2026.html                 # figure run (--no-hints, --max-usd 0.50)
cre-monitor --live bench judge bnp_q1_2026.html [--brief ID]  # judge the latest (or a given) brief
cre-monitor bench history [FILE]                              # earlier runs
```

## The answer key and moderation

One Claude call (skill model) reads the report and lists every hard figure it states that
maps onto the metric catalogue: metric, submarket, **period**, value, unit, publisher and
citation. It also writes the report's 5-8 key themes in its own words. The key holds
numbers, links and short themes only, never copied report text, so it is committed and
the team shares one moderated key.

Each figure gets **moderation signals**, computed in code:

| Signal | Meaning |
|---|---|
| **In the document** | The value really appears in the report text, in any format ("2.5m sq ft" = 2,500,000) |
| **Confidence** | The AI's own confidence that metric, place, period and value are all right |
| **Catalogue** | Known metric key, matching unit, known submarket |
| **Period ok** | The period label parses (2026-Q1, 2026-H1, 2026-08, 2026, …) |
| **Safe** | All of the above, with confidence ≥ 0.8 |

The table lists the riskiest figures first. **Accept all safe** accepts the safe ones in one
click. The analyst can then edit status, value, period or submarket, and the signals are
recomputed on save. **Only accepted figures are scored**, and the scorecard always shows how
many were accepted.

## Metrics

**Figure run** (all percentages):

| Metric | Definition |
|---|---|
| **Coverage** | Accepted figures the agent returned for the same metric, submarket and period |
| **Accuracy** | Of the figures found, those within tolerance: ±0.1 percentage points for rates, ±2% otherwise (`BENCHMARK_TOL_PP`, `BENCHMARK_TOL_REL`) |
| **Same-source / other-source accuracy** | Accuracy split by whether the agent used the report's publisher. Brokers define take-up, vacancy and availability differently, so a different broker's figure is not "wrong"; same-source accuracy is the like-for-like measure |
| **Mean absolute % error** | Average distance from the expected values, over figures found |
| **Unit correct** | Found figures recorded in the catalogue unit |
| **Grounding** | Of **all** figures the agent returned, those that appear in a tool result it actually saw during the run. Below 100% means the number came from somewhere other than its research and was possibly made up |
| **Citations contain the figure** | Of the cited pages that opened, those that contain the value. Blocked or paywalled pages count as **unverifiable**, not as failures |

**Brief judgement:**

| Metric | Definition |
|---|---|
| **Theme coverage** | Claude rates each reference theme as covered (1), partly (0.5) or missing (0); shown as a % |
| **Consistency / so-what / structure / readability** | 1-5, each with a one-line reason. Consistency ignores differences that are clearly due to a different source or period, and real contradictions are listed |
| **Readability statistics** (free) | Flesch reading ease (higher = easier; 60-70 ≈ plain English), average sentence length, % of sentences over 30 words, % of sentences with a figure that also say *when*. Shown next to the reference report's own values, which is the meaningful comparison |
| **Brief citations** (free) | The citation check applied to the brief's figures |

## Cost

A run is designed to cost **under $1** through its scope, without cutting anything off:
* the answer key is one call, made once;
* a figure run uses only the skills that collect the accepted figures, with a task tied to
  one period;
* the judge is one call on an existing brief, so no new brief is generated;
* citation and readability checks are plain code.

The estimate shown before a run is a planning figure (typical tokens × price). Afterwards,
the run records the real token usage × the price table (`MODEL_PRICES` in
[config.py](../src/cre_monitor/config.py)). Treat it as an estimate and check the prices on
anthropic.com/pricing. A warning appears when a run exceeds `BENCHMARK_TARGET_USD` (default
1.00).

`BENCHMARK_MAX_USD` (or `--max-usd`) is an **optional** cap and is off by default. When set,
no further skill is *started* once it is reached; a running skill is never interrupted.

## Reading the scorecard

* **Low coverage with high accuracy:** the agent is right when it finds figures but misses
  some. Check whether the source is reachable (blocked or paywalled) and whether the skill's
  instructions mention that publisher and metric.
* **Low same-source accuracy:** an extraction problem, e.g. the wrong number from a table or
  a mixed-up definition. Read the failing rows and sharpen the skill's *Definitions*.
* **Grounding below 100%:** inspect the ungrounded figures. They may come from model memory
  instead of research, which the research rules forbid.
* **Citations "missing":** the cited page doesn't contain the figure. It may be a wrong link,
  a figure shown only in a chart image, or a figure taken from another page.
* **Compare runs, not single numbers.** Change one thing (a skill's instructions, the model,
  the effort), rerun with the same key, and compare in **History**. Web results drift, so a
  single run is noisy.
* **With vs without citation leads:** *with* tests whether the agent can follow up a report's
  sources; *without* tests independent research and is harder.

## Limits

* It measures **retrieval and extraction of published figures** and **brief quality against
  one reference**, not forecasting ability.
* Web content changes. Period-pinned figures keep the key valid, but a source can move,
  vanish or go behind a paywall.
* The key is only as good as its moderation. Unmoderated figures are not scored.
* Judge scores are an AI opinion. Use them to compare briefs and runs with the same reference
  and rubric, and spot-check a sample by hand.
* Readability formulas are crude on financial prose, so compare with the reference's values
  rather than absolute targets.
* If a skill fails part-way, its tokens up to the failure are not recorded, so the cost is
  underestimated for that run (the failure is listed as a warning).
* Licence: reports stay git-ignored on the machine. Don't use publishers that prohibit AI
  use (e.g. Knight Frank).

## Code map

| Module | Role |
|---|---|
| `benchmark/answer_key.py` | Key models, Claude extraction, signals, edits, storage |
| `benchmark/runner.py` | Run planning, period-pinned task, figure run, brief judgement, cost |
| `benchmark/scoring.py` | Number matching, figure scoring, grounding, readability (pure) |
| `benchmark/citations.py` | Cited-page check |
| `benchmark/judge.py` | Brief rubric |
| `benchmark/store.py` | Run history (`data/benchmarks/`) |
| `ui/reference_tab.py` | 📚 Reference reports tab |
| `graph/nodes/skill_runner.py` | `run_skill(..., trace=)` keeps the transcript for grounding and tokens |

Tests: `tests/unit/test_scoring.py`, `tests/unit/test_answer_key.py`,
`tests/integration/test_benchmark_runs.py`, `tests/ui/test_reference_tab.py`.
