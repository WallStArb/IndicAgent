-- CORPUS-01 Feature Distribution Audit
-- Criteria:
-- (a) variance > epsilon (1e-12): no silent constants
-- (b) NaN rate < 5% post-warmup: exclude first 100 bars per symbol
-- (c) distributional cliff: not implemented (WARNING criterion only)

-- Step 1: Variance check for all numeric features
WITH feature_columns AS (
    SELECT column_name
    FROM information_schema.columns
    WHERE table_name = 'feature_vectors'
      AND data_type IN ('double precision','real','numeric')
      AND column_name NOT IN ('symbol','tf')
)
SELECT
    'momentum_z_fast' AS feature,
    MIN(subq.variance) AS min_variance,
    MAX(subq.variance) AS max_variance,
    COUNT(*) FILTER (WHERE subq.variance <= 1e-12) AS symbols_with_zero_variance
FROM (
    SELECT symbol, VAR_SAMP("momentum_z_fast") AS variance
    FROM feature_vectors
    GROUP BY symbol
) AS subq;

-- Note: Full audit requires iterating over all 64 features
-- This is a sample query demonstrating the approach
-- The Python script implements the full iteration
