# Contributing

This codebase is shared across the London FDE team. Please keep it easy for the next
person to read.

## Workflow
1. Create a branch: `feature/<short-description>` or `skill/<skill-name>`.
2. Make the change, with tests (`pytest` must pass offline, with no keys). Put each test in
   the folder of its type: `tests/unit`, `integration`, `e2e`, `ui`, `regression` (every
   fixed bug gets one) or `live`. See [docs/TESTING.md](docs/TESTING.md#7-writing-new-tests).
3. Update docs alongside the code:
   * the README for user-facing changes;
   * `docs/ARCHITECTURE.md` for structural changes;
   * `docs/SKILLS.md` for new tools or skill conventions.
4. Run the same checks as CI (`.github/workflows/ci.yml`) before pushing:
   ```bash
   ruff check src tests evals scripts    # lint (config in pyproject.toml)
   vulture src --min-confidence 70       # dead code
   pytest -q                             # offline tests
   python evals/run_evals.py             # evaluation set, demo mode
   ```
5. Open a PR with a summary that covers *what* changed and *why*, plus how you tested it.

## Code conventions
* Python 3.11+, type hints everywhere, `from __future__ import annotations`.
* **Every module starts with a docstring** explaining its purpose and how it fits in.
* **Public functions have Google-style docstrings** (`Args:`, `Returns:`, `Raises:`).
* Comments explain *why*, not *what*. Non-obvious decisions get a comment, e.g. why a
  reducer is custom or why a tool truncates output.
* Read configuration only via `cre_monitor.config.get_settings()`, never `os.environ`.
* Create LLMs only via `cre_monitor.llm.get_llm(tier)`, so tests can patch them.
* Every tool must:
  * work offline (fixture path);
  * never raise to the LLM (return an error string instead);
  * keep output compact.
* Graph nodes should be thin. Put logic in pure functions (e.g. `validator.validate`)
  that are easy to unit test.

## Skills
See [docs/SKILLS.md](docs/SKILLS.md). Domain experts are encouraged to improve the
Markdown instructions directly. Run `cre-monitor skills` and `pytest` before committing.

## Data & compliance
* Never commit `.env`, `data/` or `reports/`; they are git-ignored.
* Fixtures must contain only publicly available figures, with source URLs.
* Treat broker research as copyrighted. Store extracted figures and short summaries,
  not full documents.
