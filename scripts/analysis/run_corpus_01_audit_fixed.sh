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

# Get all numeric feature columns in alphabetical order
FEATURES=$(
    psql -U "$DB_USER" -h "$DB_HOST" -d "$DB_NAME" -t -A -c "
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

- **(a) Variance > epsilon (1e-12):** No silent constants. A feature is BLOCKED only if ALL symbols have variance <= epsilon.
- **(b) NaN rate < 5% post-warmup:** Excludes first 100 bars per symbol.
- **(c) No distributional cliff:** Not implemented (WARNING criterion only).

## Disposition Legend

- **PASS:** All criteria met
- **BLOCKED:** Fails criterion (a) - ALL symbols have variance <= epsilon. These features are excluded from IC measurement.
- **WARNING:** Fails criterion (b) or (c) - flagged for review but NOT dropped (Renaissance principle: never drop data that could contain signal).

## Per-Feature Audit Table

| Feature | Variance Pass | Min Variance | Max Variance | Symbols w/ Zero Var | NaN Rate % | NaN Pass | Disposition |
|---------|---------------|--------------|--------------|-------------------|------------|----------|------------|
EOF

echo "Starting feature audit..."

# Process each feature
blocked_count=0
warning_count=0
pass_count=0
total_features=0

for feature in $FEATURES; do
    total_features=$((total_features + 1))

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
            COUNT(*) FILTER (WHERE variance <= 1e-12) AS zero_var_count,
            COUNT(*) AS total_symbols
        FROM var_check;
        "
    )

    min_var=$(echo "$variance_result" | cut -d'|' -f1)
    max_var=$(echo "$variance_result" | cut -d'|' -f2)
    zero_count=$(echo "$variance_result" | cut -d'|' -f3)
    total_symbols=$(echo "$variance_result" | cut -d'|' -f4)

    # Determine variance pass: BLOCKED only if ALL symbols have variance <= epsilon
    # i.e., zero_count == total_symbols
    variance_pass="PASS"
    disposition="PASS"

    if [ "$zero_count" -eq "$total_symbols" ] 2>/dev/null; then
        # ALL symbols have zero variance - BLOCK this feature
        variance_pass="FAIL"
        disposition="BLOCKED"
        blocked_count=$((blocked_count + 1))
    else
        pass_count=$((pass_count + 1))
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

    nan_rate=$(echo "$nan_result" | xargs)

    # Handle empty result (no data after warmup)
    if [ -z "$nan_rate" ]; then
        nan_rate="N/A"
    fi

    nan_pass="PASS"
    # Check if NaN rate exceeds threshold
    if [ "$nan_rate" != "N/A" ]; then
        high_nan=$(awk "BEGIN {print ($nan_rate >= 5.0) ? 1 : 0}")
        if [ "$high_nan" -eq 1 ]; then
            nan_pass="FAIL"
            if [ "$disposition" != "BLOCKED" ]; then
                disposition="WARNING"
                warning_count=$((warning_count + 1))
                pass_count=$((pass_count - 1))
            fi
        fi
    fi

    # Write row to table
    echo "| $feature | $variance_pass | $min_var | $max_var | $zero_count / $total_symbols | $nan_rate | $nan_pass | $disposition |" >> "$OUTPUT_FILE"
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
- Cross-sectional features (momentum_rank_z, volume_rank_z, volatility_rank_z) show 100% NaN rate because they are populated by the equity_regime_model service, not feature_factory. This is expected.
EOF

echo "Audit complete. Report: $OUTPUT_FILE"
echo "Summary: $total_features audited, $blocked_count BLOCKED, $warning_count WARNING, $pass_count PASS"
