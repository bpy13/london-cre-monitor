"""Run the chat evaluation set in ``evals/questions.yaml`` and print a scorecard.

Usage::

    python evals/run_evals.py           # offline fixtures + demo mode (deterministic)
    python evals/run_evals.py --live    # live data + real LLM (needs ANTHROPIC_API_KEY)

Exit code is non-zero if any case fails, so this can gate CI or a prompt change.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import uuid
from pathlib import Path

import yaml


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true", help="Use live data and the real LLM.")
    args = parser.parse_args()

    os.environ["CRE_OFFLINE"] = "0" if args.live else "1"
    os.environ["CRE_DEMO_MODE"] = "0" if args.live else "1"
    # Keep eval runs out of the real metrics history / chat checkpoints.
    tmp = Path(tempfile.mkdtemp(prefix="cre-evals-"))
    os.environ["DATA_DIR"] = str(tmp / "data")
    os.environ["REPORTS_DIR"] = str(tmp / "reports")

    from cre_monitor.graph.builder import ask  # import after env is set

    cases = yaml.safe_load((Path(__file__).parent / "questions.yaml").read_text(encoding="utf-8"))
    failures = 0
    for i, case in enumerate(cases, 1):
        state = ask(case["question"], thread_id=f"eval-{uuid.uuid4().hex[:6]}")
        answer = state.get("answer", "")
        selected = set(state.get("selected_skills") or [])
        problems = []
        missing_skills = set(case.get("expected_skills", [])) - selected
        if missing_skills:
            problems.append(f"skills not selected: {sorted(missing_skills)}")
        for needle in case.get("must_contain", []):
            if needle.lower() not in answer.lower():
                problems.append(f"answer lacks '{needle}'")
        if "](http" not in answer:
            problems.append("no source link in answer")
        status = "PASS" if not problems else "FAIL"
        failures += bool(problems)
        print(f"[{status}] {i}. {case['question']}")
        print(f"        skills: {sorted(selected)}")
        for p in problems:
            print(f"        - {p}")
    print(f"\n{len(cases) - failures}/{len(cases)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
