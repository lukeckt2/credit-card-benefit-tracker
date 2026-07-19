#!/usr/bin/env bash
set -euo pipefail

if [[ -f ".env" ]]; then
  set -a
  . ".env"
  set +a
fi

: "${DATABASE_HOST:?DATABASE_HOST is required}"
: "${DATABASE_PORT:=3306}"
: "${DATABASE_NAME:?DATABASE_NAME is required}"
: "${DATABASE_USER:?DATABASE_USER is required}"
: "${DATABASE_PASSWORD:?DATABASE_PASSWORD is required}"

BACKUP_DIR="${BACKUP_DIR:-./backups}"
mkdir -p "${BACKUP_DIR}"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
output_path="${BACKUP_DIR}/${DATABASE_NAME}_${timestamp}.sql.gz"

MYSQL_PWD="${DATABASE_PASSWORD}" mysqldump \
  --host="${DATABASE_HOST}" \
  --port="${DATABASE_PORT}" \
  --user="${DATABASE_USER}" \
  --default-character-set=utf8mb4 \
  --single-transaction \
  --quick \
  --routines \
  --triggers \
  --events \
  "${DATABASE_NAME}" | gzip > "${output_path}"

printf '%s\n' "${output_path}"
