#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Ensure we're in the project root so Python finds the virtualenv or system packages
cd "${PROJECT_ROOT}"

echo "Running daily expiration alerts job..."
exec python3 "${SCRIPT_DIR}/expiration_alerts.py" "$@"
