#!/usr/bin/env bash
# Runs once when the codespace / dev container is created.
set -euo pipefail

echo ">>> Creating conda env 'london-cre' from environment.yml"
conda env create -f environment.yml || conda env update -f environment.yml --prune

echo ">>> Installing Chromium (used by kaleido for PNG charts in the Markdown report)"
# Optional: if this fails, PNG export is skipped with a warning; the HTML report is unaffected.
sudo apt-get update -qq && sudo apt-get install -y -qq chromium >/dev/null || \
  echo "WARNING: Chromium install failed - set REPORT_PNG=0 or run plotly_get_chrome"

echo ">>> Activating 'london-cre' by default in new terminals"
grep -q "conda activate london-cre" ~/.bashrc || echo "conda activate london-cre" >> ~/.bashrc

echo ">>> Smoke test (offline, no keys)"
/opt/conda/envs/london-cre/bin/python -m pytest -q || echo "WARNING: tests failed - see output above"

echo ">>> Done. Open a new terminal, then try: cre-monitor skills"
