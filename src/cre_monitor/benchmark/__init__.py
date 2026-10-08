"""Performance check: measure the agent's research against reference reports users supply.

Unit, integration and regression tests (tests/) prove the code behaves; this
package measures whether the agent's *answers are right*:

* :mod:`.answer_key` - AI extracts the figures and themes a reference report states;
  an analyst moderates them with quantitative signals.
* :mod:`.runner`     - run only the skills that collect those figures (period-pinned),
  score them, check citations, estimate cost; or judge an existing brief.
* :mod:`.scoring`    - figure accuracy, grounding, readability (pure functions).
* :mod:`.citations`  - does the cited page contain the figure?
* :mod:`.judge`      - Claude rubric for a brief vs the reference.
* :mod:`.store`      - run history in data/benchmarks/.

UI: 📚 Reference reports tab > 🎯 Performance check. CLI: ``cre-monitor bench``.
Metric definitions and how to read the scorecard: docs/EVALUATION.md.
"""
