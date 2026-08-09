-- Migration 309: feature_ic_scores.regime_scope / .regime schema comments (Phase 172, plan 06).
--
-- Comment-only. Idempotent by nature (COMMENT ON COLUMN always overwrites, no guard needed,
-- no row is touched). Corrects the schema documentation to describe the vocabulary this
-- table's rows actually carry after the 172-06 ic_engine.py cutover, without changing the
-- CHECK constraint, the primary key, or any existing row.
--
-- `feature_ic_scores.regime_scope`'s old comment stated `symbol_hmm` means "5 per-symbol HMM
-- labels from feature_vectors.regime" -- true before this phase, actively wrong the moment the
-- cutover ships. `regime_scope` does NOT get a new enum value for the volatility vintage:
-- `symbol_hmm` accurately names the label SOURCE (still a per-symbol GaussianHMM), and the two
-- label vocabularies (5-label trend: trending_down/transition_down/ranging/transition_up/
-- trending_up; 3-label volatility: calm/elevated/turbulent) are disjoint sets of strings, so the
-- `regime` column alone distinguishes a trend-vintage row from a volatility-vintage row. Adding a
-- fourth scope value would ripple into every `AND regime_scope = %(pass_type)s` filter the
-- shrinkage and promotion queries bind, for no discriminating power the label strings do not
-- already provide -- do not add one back for symmetry with `cross_sectional`/`pooled`.

BEGIN;

COMMENT ON COLUMN feature_ic_scores.regime_scope IS
    'Label vocabulary the regime column is drawn from: cross_sectional (9 market_regimes '
    'labels), symbol_hmm (per-symbol GaussianHMM labels from feature_vectors.regime_volatility '
    '-- calm/elevated/turbulent, K=2 or K=3, Phase 172), or pooled (the _pooled cross-regime '
    'sentinel). Derived from regime_label_source provenance, not from the label string. '
    'Rows written before Phase 172 carry the retired 5-label trend vocabulary '
    '(trending_down/transition_down/ranging/transition_up/trending_up) under the same '
    'symbol_hmm scope value -- the two vintages are distinguished by their regime string, '
    'not by regime_scope, because the two vocabularies never intersect. '
    '[schema_identifier]';

COMMENT ON COLUMN feature_ic_scores.regime IS
    'Regime label string. Vocabulary depends on regime_scope: cross_sectional rows carry one '
    'of 9 market_regimes labels; pooled rows carry the literal _pooled sentinel; symbol_hmm '
    'rows carry either the volatility vocabulary (calm/elevated/turbulent, feature_vectors.'
    'regime_volatility, Phase 172 onward) or the retired trend vocabulary '
    '(trending_down/transition_down/ranging/transition_up/trending_up, feature_vectors.regime, '
    'pre-Phase-172). The two symbol_hmm vocabularies are disjoint strings, so this column alone '
    'identifies which vintage a row belongs to. [schema_identifier]';

COMMIT;
