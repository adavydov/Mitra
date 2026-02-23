#!/usr/bin/env bash
set -euo pipefail
python3 scripts/lint_ids.py >/dev/null
python3 scripts/validate_config.py >/dev/null
pytest -q evals >/dev/null
echo "eval ok"
