#!/usr/bin/env bash
# Crontab entry:
# 5 0 1 * * PYTHON_BIN=.venv/bin/python scripts/cron_jobs/month_start_rollover.sh >> month_start_rollover.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

cd "${PROJECT_ROOT}"

if [[ -f ".env" ]]; then
  set -a
  . ".env"
  set +a
fi

ROLLOVER_MODE="${ROLLOVER_MODE:-apply}"
ROLLOVER_MONTH="${ROLLOVER_MONTH:-$(date +%Y-%m)}"
ROLLOVER_PRETTY="${ROLLOVER_PRETTY:-0}"

case "${ROLLOVER_MODE}" in
  apply|preview)
    ;;
  *)
    printf 'Invalid ROLLOVER_MODE: %s\n' "${ROLLOVER_MODE}" >&2
    exit 2
    ;;
esac

if [[ -n "${PYTHON_BIN:-}" ]]; then
  python_bin="${PYTHON_BIN}"
elif [[ -x ".venv/bin/python" ]]; then
  python_bin=".venv/bin/python"
else
  python_bin="python3"
fi

args=(
  "scripts/cron_jobs/rollover.py"
  "${ROLLOVER_MODE}"
  "--month"
  "${ROLLOVER_MONTH}"
  "--only-periods-starting-in-window"
)

if [[ "${ROLLOVER_MODE}" == "apply" ]]; then
  args+=("--yes")
fi

case "${ROLLOVER_PRETTY}" in
  1|true|TRUE|yes|YES)
    args+=("--pretty")
    ;;
esac

printf '[%s] month-start rollover mode=%s month=%s\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  "${ROLLOVER_MODE}" \
  "${ROLLOVER_MONTH}"

"${python_bin}" "${args[@]}"
