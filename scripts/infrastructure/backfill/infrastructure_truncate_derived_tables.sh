#!/usr/bin/env bash
#
# infrastructure_truncate_derived_tables.sh — truncate all derived tables
#
# Truncates all v3.0 derived data tables before a full corpus re-backfill.
# Run when starting fresh or when derived data needs complete regeneration.
# Requires database connection and user confirmation.
#

set -euo pipefail

psql() {
    PGPASSWORD=postgres command psql -U postgres -h localhost -d indicagent "$@"
}

echo "======================================"
echo " v3.0 Derived Tables Truncation"
echo " $(date)"
echo "======================================"
echo

echo "Current row counts:"
psql -c "
SELECT 'feature_vectors'    AS table_name, count(*) AS rows FROM feature_vectors
UNION ALL
SELECT 'forward_returns',   count(*) FROM forward_returns
UNION ALL
SELECT 'feature_ic_scores', count(*) FROM feature_ic_scores
UNION ALL
SELECT 'backfill_status',   count(*) FROM backfill_status
UNION ALL
SELECT 'ensemble_weights',  count(*) FROM ensemble_weights
UNION ALL
SELECT 'ensemble_alpha',    count(*) FROM ensemble_alpha
UNION ALL
SELECT 'alpha_events',      count(*) FROM alpha_events
ORDER BY table_name;"

echo
read -r -p "Truncate all six tables? This cannot be undone. [y/N] " confirm
if [[ "${confirm,,}" != "y" ]]; then
    echo "Aborted."
    exit 0
fi

echo
echo "Truncating..."

psql -c "TRUNCATE alpha_events;"      && echo "  - alpha_events: done"
psql -c "TRUNCATE ensemble_alpha;"    && echo "  - ensemble_alpha: done"
psql -c "TRUNCATE ensemble_weights;"  && echo "  - ensemble_weights: done"
psql -c "TRUNCATE feature_ic_scores;" && echo "  - feature_ic_scores: done"
psql -c "TRUNCATE forward_returns;"   && echo "  - forward_returns: done"
psql -c "TRUNCATE feature_vectors;"   && echo "  - feature_vectors: done"
psql -c "TRUNCATE backfill_status;"   && echo "  - backfill_status: done"

echo
echo "Verifying..."
psql -c "
SELECT 'feature_vectors'    AS table_name, count(*) AS rows FROM feature_vectors
UNION ALL
SELECT 'forward_returns',   count(*) FROM forward_returns
UNION ALL
SELECT 'feature_ic_scores', count(*) FROM feature_ic_scores
UNION ALL
SELECT 'backfill_status',   count(*) FROM backfill_status
UNION ALL
SELECT 'ensemble_weights',  count(*) FROM ensemble_weights
UNION ALL
SELECT 'ensemble_alpha',    count(*) FROM ensemble_alpha
UNION ALL
SELECT 'alpha_events',      count(*) FROM alpha_events
ORDER BY table_name;"

echo
echo " Done. $(date)"
echo "======================================"
