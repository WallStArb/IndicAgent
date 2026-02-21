#!/usr/bin/env bash
# IndicAgent DB Setup Script
# Version: 1.1.0
# Last Updated: 2026-02-21
# Status: Current ✅
#
# Runs the full schema setup for a new machine:
#   1. Base schema (create_schema.sql) — core tables including signal_ledger
#   2. Numbered migrations (production/migrations/0*.sql) — incremental changes
#
# Usage:
#   bash production/scripts/db_setup.sh
#   DATABASE_URL=postgresql://... bash production/scripts/db_setup.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")"/../.. && pwd)"
SCHEMAS_DIR="$PROJECT_ROOT/production/schemas"
MIGRATIONS_DIR="$PROJECT_ROOT/production/migrations"

DB_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/indicagent}"

echo "=== IndicAgent DB Setup ==="
echo "Using DATABASE_URL=$DB_URL"

# Step 1: Base schema (idempotent — uses IF NOT EXISTS throughout)
echo ""
echo ">> Applying base schema (create_schema.sql)..."
psql "$DB_URL" -f "$SCHEMAS_DIR/create_schema.sql" | cat

# Step 2: Numbered migrations in order (idempotent)
shopt -s nullglob
mapfile -t MIGS < <(ls -1 "$MIGRATIONS_DIR"/[0-9][0-9][0-9]_*.sql | sort)
shopt -u nullglob

if [[ ${#MIGS[@]} -eq 0 ]]; then
  echo "No numbered migration files found in $MIGRATIONS_DIR"
else
  for mig in "${MIGS[@]}"; do
    echo ""
    echo ">> Applying $(basename "$mig")..."
    psql "$DB_URL" -f "$mig" | cat
  done
fi

echo ""
echo "✅ DB setup complete"

