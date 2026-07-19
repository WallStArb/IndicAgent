-- Migration 187: feature_ic_scores.regime_scope -- disambiguate the two regime label
-- vocabularies that share the `regime` column (todo 141.1-02, RSCOPE-01).
--
-- feature_ic_scores.regime currently mixes two disjoint label vocabularies with no
-- scope qualifier: the 9 cross-sectional labels from market_regimes (e.g. high_bull,
-- low_bear) and the 5 per-symbol HMM labels from feature_vectors.regime (e.g.
-- trending_up, ranging), plus the _pooled cross-regime sentinel. A consumer that
-- filters on regime alone cannot tell which system produced a row. This migration adds
-- a regime_scope column that disambiguates cross_sectional vs symbol_hmm vs pooled.
--
-- Purely additive: no PK change, no partial-index change, no read-path change.
-- Idempotent: safe to re-run.

-- 1. Add column ----------------------------------------------------------------

ALTER TABLE feature_ic_scores ADD COLUMN IF NOT EXISTS regime_scope text;

-- 2. Backfill existing rows -----------------------------------------------------
--
-- regime_scope is derived from the EXISTING regime_label_source provenance column,
-- NOT a bare pooled/non-pooled split. The live corpus contains historical per-symbol
-- HMM rows (regime_label_source='forward_filter', is_pooled=false) that a bare split
-- would have misclassified as cross_sectional -- AGY verified this failure mode
-- against live DIA/EEM/SPY rows. Mapping: the _pooled sentinel (incl. context_features
-- pooled rows) -> pooled; market_regimes-sourced or POOLED-symbol rows ->
-- cross_sectional; forward_filter-sourced non-pooled rows -> symbol_hmm. A future
-- corpus built with equity_model_enabled=False gets the correct scope at insert time
-- from _resolve_regime_scope (services/ic_engine.py), so backfill and insert-time
-- paths stay consistent.

UPDATE feature_ic_scores SET regime_scope = CASE
    WHEN regime = '_pooled' THEN 'pooled'
    WHEN symbol = 'POOLED' OR regime_label_source = 'market_regimes' THEN 'cross_sectional'
    WHEN regime_label_source = 'forward_filter' THEN 'symbol_hmm'
    ELSE 'cross_sectional'
END WHERE regime_scope IS NULL;

-- 3. NOT NULL ---------------------------------------------------------------

ALTER TABLE feature_ic_scores ALTER COLUMN regime_scope SET NOT NULL;

-- 4. CHECK constraint (idempotent drop-then-add) ---------------------------------

ALTER TABLE feature_ic_scores DROP CONSTRAINT IF EXISTS feature_ic_scores_regime_scope_chk;

ALTER TABLE feature_ic_scores ADD CONSTRAINT feature_ic_scores_regime_scope_chk
    CHECK (regime_scope IN ('cross_sectional', 'symbol_hmm', 'pooled'));

-- 5. Sync-validation assertion ---------------------------------------------------
-- Loud failure if the backfill ever diverges from the regime_label_source mapping.

DO $$
DECLARE mismatches bigint;
BEGIN
  SELECT count(*) INTO mismatches FROM feature_ic_scores
  WHERE regime_scope IS DISTINCT FROM (CASE
      WHEN regime = '_pooled' THEN 'pooled'
      WHEN symbol = 'POOLED' OR regime_label_source = 'market_regimes' THEN 'cross_sectional'
      WHEN regime_label_source = 'forward_filter' THEN 'symbol_hmm'
      ELSE 'cross_sectional'
  END);
  IF mismatches > 0 THEN
    RAISE EXCEPTION 'regime_scope backfill out of sync with regime_label_source mapping: % rows', mismatches;
  END IF;
END $$;

-- 6. Column comment ---------------------------------------------------------------

COMMENT ON COLUMN feature_ic_scores.regime_scope IS
  'Label vocabulary the regime column is drawn from: cross_sectional (9 market_regimes '
  'labels), symbol_hmm (5 per-symbol HMM labels from feature_vectors.regime), or pooled '
  '(the _pooled cross-regime sentinel). Derived from regime_label_source provenance, not '
  'from the label string. Disambiguates the two regime systems that share the regime '
  'column. [schema_identifier]';
