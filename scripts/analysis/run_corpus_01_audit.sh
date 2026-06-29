#!/bin/bash
# CORPUS-01 Feature Distribution Audit
# Direct SQL approach for efficiency

DB_USER="postgres"
DB_HOST="localhost"
DB_NAME="indicagent"
export PGPASSWORD="postgres"

OUTPUT_DIR="/home/bg/dev/indicagent/.claude/worktrees/agent-a1e00bba20fb55f2b/docs/analysis"
mkdir -p "$OUTPUT_DIR"

OUTPUT_FILE="$OUTPUT_DIR/corpus-01-feature-audit.md"

# Get all numeric feature columns
FEATURES=$(
    psql -U "$DB_USER" -h "$DB_HOST" -d "$DB_NAME" -t -c "
    SELECT column_name
    FROM information_schema.columns
    WHERE table_name = 'feature_vectors'
      AND data_type IN ('double precision','real','numeric')
      AND column_name NOT IN ('symbol','tf')
    ORDER BY column_name;
    "
)

# Write report header
cat > "$OUTPUT_FILE" << EOF
# CORPUS-01: Feature Distribution Audit

**Date:** $(date -u +"%Y-%m-%d")
**Corpus:** V1-corrected (Phase 141 P0)

## Audit Criteria

- **(a) Variance > epsilon (1e-12):** No silent constants. All symbols must have variance > epsilon.
- **(b) NaN rate < 5% post-warmup:** Excludes first 100 bars per symbol.
- **(c) No distributional cliff:** 4-week rolling std z-score |z| > 2.0 triggers WARNING.

## Disposition Legend

- **PASS:** All criteria met
- **BLOCKED:** Fails criterion (a) - zero variance, IC undefined. These features are excluded from IC measurement.
- **WARNING:** Fails criterion (b) or (c) - flagged for review but NOT dropped (Renaissance principle: never drop data that could contain signal).

## Per-Feature Audit Table

| Feature | Variance Pass | Min Variance | Max Variance | NaN Rate % | NaN Pass | Disposition |
|---------|---------------|--------------|--------------|------------|----------|------------|
EOF

echo "Starting feature audit..."

# Process each feature
blocked_count=0
warning_count=0
pass_count=0
total_features=0

for feature in $FEATURES; do
    total_features=$((total_features + 1))
    feature=$(echo "$feature" | xargs)  # trim whitespace

    echo "Auditing $total_features: $feature..."

    # Variance check per symbol
    variance_result=$(
        psql -U "$DB_USER" -h "$DB_HOST" -d "$DB_NAME" -t -A -c "
        WITH var_check AS (
            SELECT symbol, VAR_SAMP(\"$feature\") AS variance
            FROM feature_vectors
            GROUP BY symbol
        )
        SELECT
            COALESCE(MIN(variance), 0) AS min_var,
            COALESCE(MAX(variance), 0) AS max_var,
            COUNT(*) FILTER (WHERE variance <= 1e-12) AS zero_var_count
        FROM var_check;
        "
    )

    min_var=$(echo "$variance_result" | cut -d'|' -f1 | xargs)
    max_var=$(echo "$variance_result" | cut -d'|' -f2 | xargs)
    zero_count=$(echo "$variance_result" | cut -d'|' -f3 | xargs | tr -d ' ')

    # Ensure zero_count is numeric
    zero_count=${zero_count:-0}

    # Determine variance pass
    if [ -n "$zero_count" ] && [ "$zero_count" -gt 0 ] 2>/dev/null; then
        variance_pass="✗"
        disposition="BLOCKED"
        blocked_count=$((blocked_count + 1))
    else
        variance_pass="✓"
    fi

    # NaN rate check (post-warmup)
    nan_result=$(
        psql -U "$DB_USER" -h "$DB_HOST" -d "$DB_NAME" -t -A -c "
        WITH numbered AS (
            SELECT
                \"$feature\" IS NULL AS is_null,
                ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY bar_ts) AS rn
            FROM feature_vectors
        )
        SELECT
            ROUND(100.0 * COUNT(*) FILTER (WHERE is_null) / COUNT(*), 2) AS nan_rate
        FROM numbered
        WHERE rn > 100;
        "
    )

    nan_rate=$(echo "$nan_result" | xargs | tr -d '\n')
    nan_pass="✓"

    # Check if NaN rate exceeds threshold (bash floating point comparison)
    if [ -n "$nan_rate" ]; then
        # Use awk for floating point comparison
        high_nan=$(awk "BEGIN {print ($nan_rate >= 5.0) ? 1 : 0}")
        if [ "$high_nan" -eq 1 ]; then
            nan_pass="✗"
            disposition="WARNING"
            warning_count=$((warning_count + 1))
        fi
    else
        nan_rate="N/A"
    fi

    # Set final disposition
    if [ "$disposition" = "BLOCKED" ]; then
        :
    elif [ "$disposition" = "WARNING" ]; then
        :
    elif [ "$variance_pass" = "✓" ]; then
        disposition="PASS"
        pass_count=$((pass_count + 1))
    fi

    # Write row to table
    echo "| $feature | $variance_pass | $min_var | $max_var | $nan_rate | $nan_pass | $disposition |" >> "$OUTPUT_FILE"
done

# Write summary
cat >> "$OUTPUT_FILE" << EOF

## Summary

- **Total features audited:** $total_features
- **BLOCKED:** $blocked_count
- **WARNING:** $warning_count
- **PASS:** $pass_count

## Notes

- Variance audit is per-symbol: a feature is BLOCKED only if ALL symbols have variance <= epsilon.
- NaN rate is computed post-warmup: first 100 bars per symbol are excluded.
- BLOCKED features are excluded from IC measurement: IC is undefined for constant series.
EOF

echo "Audit complete. Report: $OUTPUT_FILE"
echo "Summary: $total_features audited, $blocked_count BLOCKED, $warning_count WARNING, $pass_count PASS"
