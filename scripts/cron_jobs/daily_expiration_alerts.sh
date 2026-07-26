#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Ensure we're in the project root so Python finds the virtualenv or system packages
cd "${PROJECT_ROOT}"

if [[ -n "${PYTHON_BIN:-}" ]]; then
  python_bin="${PYTHON_BIN}"
elif [[ -x ".venv/bin/python" ]]; then
  python_bin=".venv/bin/python"
else
  python_bin="python3"
fi

echo "Running daily expiration alerts job..."
exec "${python_bin}" "${SCRIPT_DIR}/expiration_alerts.py" "$@"
