-- Migration 345: factor_series_correlation table -- pairwise correlation among
-- TagCalibrator's measurable factor_series proxies (Phase 174 cross-asset follow-on).
--
-- Root problem this fixes: tag_vocabulary treats its 12+ measurable (beta_regression)
-- tags as flatly independent, but several are empirically the same underlying theme
-- wearing different names -- verified live 2026-09-16: rate_sensitive's proxy (TLT) vs
-- yield_curve's proxy (IEF-SHY) correlate at 0.939. Nothing before this migration stored
-- that fact; it had to be re-derived ad hoc in conversation. This table makes it a
-- durable, queryable, TagCalibrator-maintained artifact instead.
--
-- Scope: factor_series values only (currently ~12-18, one per measurable tag in
-- tag_vocabulary) -- NOT a general instrument-correlation table. That already exists at
-- the ad hoc script level (scripts/analysis/universe_expansion_correlation_structure_check.py)
-- for arbitrary candidate baskets; this table is specifically for the small, stable set of
-- named macro/factor proxies TagCalibrator itself already constructs every run.
--
-- factor_a < factor_b is enforced so each unordered pair has exactly one row (never both
-- (A,B) and (B,A)); self-pairs are never written (TagCalibrator's own correlation-computation
-- code skips them, not enforced here since text ordering can't express "different value").
--
-- No APR threshold accompanies this table deliberately: it stores measured correlations
-- only, not a pass/fail "same cluster" decision -- consumers apply their own cutoff at
-- query time (Musk mandate: don't build a decision layer nobody has asked for yet).
--
-- Idempotent: CREATE TABLE IF NOT EXISTS, safe to re-run.

BEGIN;

CREATE TABLE IF NOT EXISTS factor_series_correlation (
    factor_a TEXT NOT NULL,
    factor_b TEXT NOT NULL,
    correlation DOUBLE PRECISION NOT NULL,
    n_obs INTEGER NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (factor_a, factor_b),
    CHECK (factor_a < factor_b)
);

COMMIT;
