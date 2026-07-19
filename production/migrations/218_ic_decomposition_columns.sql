-- Migration 218: IC decomposition columns — Phase 143.1 Plan 05 (todo 090, Component B)
--
-- Adds two diagnostic-only columns to feature_ic_scores: sign_hit_rate (directional
-- accuracy — fraction of bars where sign(prediction) == sign(realized return)) and
-- magnitude_conditional_ic (IC recomputed over the subset of bars where |prediction|
-- is above the top-quartile threshold — magnitude alignment). Decomposes a single IC
-- value into "gets the direction right" vs "gets the magnitude right when it matters,"
-- sharpening Phase 143's decay monitors. Computed in the existing corpus IC loop
-- (services/ic_engine.py) reusing src/intelligence/statistics/ic_math.py's
-- _vectorized_ic — no re-derived Spearman, no new query, no new eligibility/gate
-- predicate. Both columns are nullable: NaN/undefined cases (zero valid nonzero-sign
-- observations, a thresholded subset with <2 observations, degenerate variance)
-- persist as SQL NULL, same convention as ic_sharpe/ic_sortino on this table.
--
-- Migration numbering note: 220-224 already claimed by prior 143.1 plans (221 by a
-- concurrent sibling not yet merged here). 225 is the verified next-free number as of
-- this plan's execution (see todo 095 — directory-split collision risk).

BEGIN;

ALTER TABLE feature_ic_scores ADD COLUMN IF NOT EXISTS sign_hit_rate DOUBLE PRECISION;
ALTER TABLE feature_ic_scores ADD COLUMN IF NOT EXISTS magnitude_conditional_ic DOUBLE PRECISION;

COMMENT ON COLUMN feature_ic_scores.sign_hit_rate IS
    'Directional-accuracy diagnostic (Component B, todo 090): fraction of bars where '
    'sign(prediction) == sign(realized return), in [0, 1]. NULL when a cell has zero '
    'valid (nonzero-sign) observations. Diagnostic only — no eligibility/gate predicate '
    'reads this column.';

COMMENT ON COLUMN feature_ic_scores.magnitude_conditional_ic IS
    'Magnitude-alignment diagnostic (Component B, todo 090): IC recomputed over the '
    'subset of bars where |prediction| is in the top quartile (75th percentile) per '
    'feature, reusing _vectorized_ic on the re-ranked subset. NULL when the '
    'thresholded subset has fewer than 2 observations or is degenerate. Diagnostic '
    'only — no eligibility/gate predicate reads this column.';

COMMIT;
