#!/usr/bin/env bash
# Truncate all v3.0 derived data tables (feature_vectors, forward_returns,
# feature_ic_scores, backfill_status). Run this before a full corpus re-backfill.
# Usage: bash production/scripts/truncate_derived_tables.sh

set -euo pipefail

PSQL="PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent"

echo "======================================"
echo " v3.0 Derived Tables Truncation"
echo " $(date)"
echo "======================================"
echo

# Show current row counts
echo "Current row counts:"
eval "$PSQL" -c "
SELECT 'feature_vectors'   AS table_name, count(*) AS rows FROM feature_vectors
UNION ALL
SELECT 'forward_returns',  count(*) FROM forward_returns
UNION ALL
SELECT 'feature_ic_scores', count(*) FROM feature_ic_scores
UNION ALL
SELECT 'backfill_status',  count(*) FROM backfill_status
ORDER BY table_name;"

echo
read -r -p "Truncate all four tables? This cannot be undone. [y/N] " confirm
if [[ "${confirm,,}" != "y" ]]; then
    echo "Aborted."
    exit 0
fi

echo
echo "Truncating..."

eval "$PSQL" -c "TRUNCATE feature_ic_scores;" && echo "  - feature_ic_scores: done"
eval "$PSQL" -c "TRUNCATE forward_returns;"   && echo "  - forward_returns: done"
eval "$PSQL" -c "TRUNCATE feature_vectors;"   && echo "  - feature_vectors: done"
eval "$PSQL" -c "TRUNCATE backfill_status;"   && echo "  - backfill_status: done"

echo
echo "Verifying..."
eval "$PSQL" -c "
SELECT 'feature_vectors'   AS table_name, count(*) AS rows FROM feature_vectors
UNION ALL
SELECT 'forward_returns',  count(*) FROM forward_returns
UNION ALL
SELECT 'feature_ic_scores', count(*) FROM feature_ic_scores
UNION ALL
SELECT 'backfill_status',  count(*) FROM backfill_status
ORDER BY table_name;"

echo
echo " Done. $(date)"
echo "======================================"
