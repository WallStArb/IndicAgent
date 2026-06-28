#!/usr/bin/env bash
#
# infrastructure_db_setup.sh — database schema initialization
#
# Applies all numbered migrations in order to initialize TimescaleDB schema.
# Run once on fresh database installation or after major schema migrations.
# Requires psql client and TimescaleDB extension installed.
#

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

