-- Migration 575: one IC table name (lead assignment 2026-11-04, same pattern as 570; takes over
-- the drop half of plan 186-28).
--
-- The legacy feature_ic_scores (10,616,092 rows, last computed_at 2026-09-24, written by the
-- deleted ic_engine chain) is dead cache: its summary card is
-- docs/research/summary-cards/cache-feature-ic-scores-v1.md (186-01, D-06), which records the
-- per-scope counts, and tests/unit/test_summary_cards.py DROP_TABLES covers it. Counts checked
-- live before the drop, equal to the card: cross_sectional 5,540,805 + pooled 119,680;
-- earnings_season 2,188,440 + pooled 210,600; pooled 971,073; symbol_hmm 1,585,494; one
-- training_window_end value (alpha.validation.oos_start, the legacy meaning). The research
-- ledger was reset on 2026-10-30, so no counted result depends on it.
--
-- Its two views, feature_edge_by_regime and feature_edge_by_symbol (pg_depend 2026-11-04), have
-- no reader in src, services, scripts, tests or systemd units; they drop with it.
--
-- The empty feature_ic_scores_v2 (migration 413: regime_scope in the primary key, sole writer
-- services/ic_measure.py through bulk_load) takes the name. Its two indexes and 17 non-key
-- constraints are renamed one statement each (the pkey constraint follows its index); its column
-- comments, compression settings and 30-day chunks move with the table. No compression
-- policy, as in 413: bulk_load refuses a range a scheduled policy covers.
-- No provenance_batch row names either table.
--
-- Nothing here decompresses or alters a column type, so no VACUUM step (D-16).
--
-- Not guarded (unlike 570): feature_ic_scores_v2 is in the 433 integration baseline and no later
-- migration drops it, so a database without it is wrong, and the swap fails loudly there instead
-- of leaving the ic_engine-era table under the name every reader now targets.

BEGIN;

DROP VIEW IF EXISTS feature_edge_by_regime;
DROP VIEW IF EXISTS feature_edge_by_symbol;
DROP TABLE feature_ic_scores;

ALTER TABLE feature_ic_scores_v2 RENAME TO feature_ic_scores;

ALTER INDEX feature_ic_scores_v2_pkey RENAME TO feature_ic_scores_pkey;
ALTER INDEX feature_ic_scores_v2_training_window_end_idx
    RENAME TO feature_ic_scores_training_window_end_idx;
ALTER TABLE feature_ic_scores RENAME CONSTRAINT feature_ic_scores_v2_computed_at_not_null
    TO feature_ic_scores_computed_at_not_null;
ALTER TABLE feature_ic_scores RENAME CONSTRAINT feature_ic_scores_v2_feature_name_not_null
    TO feature_ic_scores_feature_name_not_null;
ALTER TABLE feature_ic_scores RENAME CONSTRAINT feature_ic_scores_v2_feature_status_at_eval_not_null
    TO feature_ic_scores_feature_status_at_eval_not_null;
ALTER TABLE feature_ic_scores RENAME CONSTRAINT feature_ic_scores_v2_fresh_scope_pooled_chk
    TO feature_ic_scores_fresh_scope_pooled_chk;
ALTER TABLE feature_ic_scores RENAME CONSTRAINT feature_ic_scores_v2_is_pooled_not_null
    TO feature_ic_scores_is_pooled_not_null;
ALTER TABLE feature_ic_scores RENAME CONSTRAINT feature_ic_scores_v2_lookahead_bars_not_null
    TO feature_ic_scores_lookahead_bars_not_null;
ALTER TABLE feature_ic_scores RENAME CONSTRAINT feature_ic_scores_v2_n_independent_not_null
    TO feature_ic_scores_n_independent_not_null;
ALTER TABLE feature_ic_scores RENAME CONSTRAINT feature_ic_scores_v2_regime_label_source_not_null
    TO feature_ic_scores_regime_label_source_not_null;
ALTER TABLE feature_ic_scores RENAME CONSTRAINT feature_ic_scores_v2_regime_not_null
    TO feature_ic_scores_regime_not_null;
ALTER TABLE feature_ic_scores RENAME CONSTRAINT feature_ic_scores_v2_regime_scope_chk
    TO feature_ic_scores_regime_scope_chk;
ALTER TABLE feature_ic_scores RENAME CONSTRAINT feature_ic_scores_v2_regime_scope_not_null
    TO feature_ic_scores_regime_scope_not_null;
ALTER TABLE feature_ic_scores RENAME CONSTRAINT feature_ic_scores_v2_reliable_not_null
    TO feature_ic_scores_reliable_not_null;
ALTER TABLE feature_ic_scores RENAME CONSTRAINT feature_ic_scores_v2_shrinkage_weight_unit_interval_chk
    TO feature_ic_scores_shrinkage_weight_unit_interval_chk;
ALTER TABLE feature_ic_scores RENAME CONSTRAINT feature_ic_scores_v2_symbol_not_null
    TO feature_ic_scores_symbol_not_null;
ALTER TABLE feature_ic_scores RENAME CONSTRAINT feature_ic_scores_v2_tf_not_null
    TO feature_ic_scores_tf_not_null;
ALTER TABLE feature_ic_scores RENAME CONSTRAINT feature_ic_scores_v2_training_window_end_not_null
    TO feature_ic_scores_training_window_end_not_null;
ALTER TABLE feature_ic_scores RENAME CONSTRAINT feature_ic_scores_v2_vector_domain_not_null
    TO feature_ic_scores_vector_domain_not_null;

COMMENT ON TABLE feature_ic_scores IS
    'Fresh IC scores (phase 186, migration 413; the name since migration 575): '
    'regime_scope is in the primary key. Sole writer services/ic_measure.py via '
    'bulk_load(). training_window_end is the latest target exit bar a cell used, '
    'always before alpha.validation.oos_start (D-19).';

UPDATE config_schema
   SET description = replace(description, 'feature_ic_scores_v2', 'feature_ic_scores')
 WHERE description LIKE '%feature\_ic\_scores\_v2%';

COMMIT;
