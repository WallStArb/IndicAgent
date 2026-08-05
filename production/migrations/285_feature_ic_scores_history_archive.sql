-- Migration 285: feature_ic_scores_history -- archive table for todo 252
--
-- ic_engine.py's fingerprint invalidation (_FINGERPRINT_INVALIDATE_DELETE_SQL /
-- _FINGERPRINT_INVALIDATE_DELETE_CROSS_SECTIONAL_SQL) hard-deletes feature_ic_scores rows
-- with no archive whenever code or APR config changes for an already-computed
-- training_window_end -- the prior measurement is gone the moment the new one lands.
-- Directly violates this project's "never drop data that could contain signal" principle.
--
-- Fix: archive-before-delete (todo 252's recommended, lower-risk option -- the smallest
-- schema change; feature_ic_scores' own PK/query shape stays untouched for every existing
-- consumer, unlike the rejected alternative of folding the fingerprint into feature_ic_scores'
-- own row identity, which would touch every reader).
--
-- Columns mirror feature_ic_scores exactly, plus:
--   archived_at                  -- when this row was archived (immediately before deletion)
--   archived_code_content_key    -- the ic_cell_fingerprints tuple that PRODUCED this row,
--   archived_apr_snapshot_key       captured just before ic_engine.py's post-recompute UPSERT
--   archived_upstream_watermark     overwrites it -- reuses ic_cell_fingerprints' existing
--                                    provenance convention rather than inventing a second one
--                                    (todo 252's explicit recommendation). NULL only in the
--                                    (should-not-occur-in-practice) case of an archived row
--                                    whose fingerprint was never recorded.
--
-- No FK to feature_ic_scores (same precedent as alpha_frames/construction_spreads -- an FK
-- would either block the very DELETE this table exists to make safe, or CASCADE-wipe the
-- archive along with it). No unique constraint: multiple invalidate-then-recompute cycles for
-- the same (feature_name, symbol, tf, regime, lookahead_bars, training_window_end) cell each
-- add a new archived snapshot -- an append-only ledger, not a single-slot backup.

CREATE TABLE feature_ic_scores_history (
    feature_name             text                      NOT NULL,
    vector_domain             text                      NOT NULL,
    symbol                    text                      NOT NULL,
    tf                        text                      NOT NULL,
    regime                    text                      NOT NULL,
    lookahead_bars            integer                   NOT NULL,
    training_window_end       timestamptz               NOT NULL,
    is_pooled                 boolean                   NOT NULL,
    n_independent             integer                   NOT NULL,
    reliable                  boolean                   NOT NULL,
    ic_value                  double precision,
    ic_sign                   smallint,
    p_value                   double precision,
    ic_ci_lower               double precision,
    ic_ci_upper               double precision,
    passes_ci_gate            boolean,
    bh_adjusted_p             double precision,
    passes_fdr                boolean,
    wf_fold_count             integer,
    wf_pass_count             integer,
    wf_ic_sharpe              double precision,
    passes_walkforward        boolean,
    ic_sharpe                 double precision,
    ic_sharpe_n_windows       integer,
    regime_label_source       text                      NOT NULL,
    computed_at               timestamptz               NOT NULL,
    ic_sortino                double precision,
    ic_win_rate               double precision,
    cluster_id                smallint,
    feature_status_at_eval    text                      NOT NULL,
    ic_sharpe_hac             double precision,
    regime_scope              text                      NOT NULL,
    ic_shrunk                 double precision,
    shrinkage_weight          double precision,
    partial_ic                double precision,
    partial_ic_p_value        double precision,
    partial_ic_n              integer,
    passes_partial_fdr        boolean,
    sign_hit_rate             double precision,
    magnitude_conditional_ic  double precision,
    cumulative_e_value        double precision,
    archived_at               timestamptz               NOT NULL DEFAULT now(),
    archived_code_content_key    text,
    archived_apr_snapshot_key    text,
    archived_upstream_watermark  jsonb
);

-- Matches feature_ic_scores_symbol_tf_ts_idx's shape -- the natural lookup path ("show me
-- every archived version of this cell's history"), plus archived_at DESC so the most recent
-- supersession surfaces first.
CREATE INDEX feature_ic_scores_history_cell_idx
    ON feature_ic_scores_history (feature_name, symbol, tf, regime, lookahead_bars, training_window_end, archived_at DESC);
