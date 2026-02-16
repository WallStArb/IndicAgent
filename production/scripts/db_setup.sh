#!/usr/bin/env bash
# IndicAgent DB Setup Script
# Version: 1.0.0
# Last Updated: 2025-08-08
# Status: Current ✅

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")"/../.. && pwd)"
MIGRATIONS_DIR="$PROJECT_ROOT/production/migrations"

DB_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/indicagent}"

echo "=== IndicAgent DB Setup ==="
echo "Using DATABASE_URL=$DB_URL"
echo "Migrations dir: $MIGRATIONS_DIR"

shopt -s nullglob
mapfile -t MIGS < <(ls -1 "$MIGRATIONS_DIR"/[0-9][0-9][0-9]_*.sql | sort)
shopt -u nullglob

if [[ ${#MIGS[@]} -eq 0 ]]; then
  echo "No migration files found in $MIGRATIONS_DIR"
  exit 1
fi

for mig in "${MIGS[@]}"; do
  echo "\n>> Applying $(basename "$mig")"
  psql "$DB_URL" -v ON_ERROR_STOP=1 -f "$mig" | cat
done

echo "\n✅ All migrations applied"

