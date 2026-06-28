#!/usr/bin/env bash
# IndicAgent DB Setup Script
# Version: 1.2.0
# Last Updated: 2026-05-30
# Status: Current ✅
#
# Applies all numbered migrations in order. Migrations are idempotent (IF NOT EXISTS).
# Two migration homes:
#   production/migrations/ — legacy (001–103), frozen
#   db/migrations/         — canonical (Phase 104+)
#
# Usage:
#   bash scripts/infrastructure/setup/infrastructure_db_setup.sh
#   DATABASE_URL=postgresql://... bash scripts/infrastructure/setup/infrastructure_db_setup.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")"/../.. && pwd)"

DB_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/indicagent}"

echo "=== IndicAgent DB Setup ==="
echo "Using DATABASE_URL=$DB_URL"

shopt -s nullglob
mapfile -t MIGS < <(ls -1 \
  "$PROJECT_ROOT/production/migrations"/[0-9][0-9][0-9]_*.sql \
  "$PROJECT_ROOT/db/migrations"/[0-9][0-9][0-9]_*.sql \
  | sort -t/ -k1,1)
shopt -u nullglob

if [[ ${#MIGS[@]} -eq 0 ]]; then
  echo "No migration files found"
  exit 1
fi

for mig in "${MIGS[@]}"; do
  echo ""
  echo ">> Applying $(basename "$mig")..."
  psql "$DB_URL" -f "$mig" | cat
done

echo ""
echo "✅ DB setup complete"

