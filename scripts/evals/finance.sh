#!/usr/bin/env bash
set -euo pipefail

python3 scripts/lint_ids/lint_ids.py >/dev/null
python3 scripts/validate_config/validate_config.py >/dev/null
echo "eval ok"
