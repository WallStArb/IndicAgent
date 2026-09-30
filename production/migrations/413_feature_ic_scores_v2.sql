-- Migration 413: feature_ic_scores_v2, the fresh IC table with regime_scope in the PK from
-- creation (phase 186 plan 14, todo 391, D-20)
--
-- Design: .planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-CONTEXT.md
-- (D-17, D-19, D-20, D-23, D-24) and docs/plans/2026-09-26-unified-research-to-production-design.md
-- section 14.6 item 2.
--
-- Sole writer: services/ic_measure.py, only through bulk_load() (one provenance_batch row per
-- unit). Nothing else may INSERT into or UPDATE this table.
--
-- The legacy feature_ic_scores table is NOT touched here: no decompress, no recompress, no
-- ALTER, no VACUUM. Its 10,616,092 rows carry a different meaning of training_window_end (a bar
-- bound equal to alpha.validation.oos_start) and stay frozen until plan 186-28 drops the table
-- whole. A separate table is what keeps the two meanings from ever sharing a column.
--
-- Meaning of training_window_end in this table: the latest target exit bar used by the cell,
-- always strictly before alpha.validation.oos_start, so "no target window reaches oos_start"
-- (D-19) is the query training_window_end < oos_start.
--
-- Primary key: regime_scope is part of it from creation (todo 391). Three fresh scopes only:
-- unstratified (proposer cells), regime_volatility (disclosure) and member_window (monitoring).
-- The legacy scope values cannot enter this table.
--
-- Compression mirrors the legacy table (segmentby symbol,tf; orderby training_window_end DESC;
-- 30-day chunks). No scheduled compression policy: bulk_load refuses a range under a scheduled
-- policy, and the writer's write session compresses what it wrote on exit.
--
-- Volume: empty at creation. The fresh run (186-28) writes on the order of the proposer's
-- features x horizons x tfs plus regime labels, well under the legacy table's row count.
-- Not idempotent on purpose: a second apply fails loudly on CREATE TABLE.

BEGIN;

CREATE TABLE feature_ic_scores_v2 (
    feature_name             text             NOT NULL,
    vector_domain            text             NOT NULL,
    symbol                   text             NOT NULL,
    tf                       text             NOT NULL,
    regime                   text             NOT NULL,
    lookahead_bars           integer          NOT NULL,
    training_window_end      timestamptz      NOT NULL,
    is_pooled                boolean          NOT NULL DEFAULT false,
    n_independent            integer          NOT NULL,
    reliable                 boolean          NOT NULL,
    ic_value                 double precision,
    ic_sign                  smallint,
    p_value                  double precision,
    ic_ci_lower              double precision,
    ic_ci_upper              double precision,
    passes_ci_gate           boolean,
    bh_adjusted_p            double precision,
    passes_fdr               boolean,
    wf_fold_count            integer,
    wf_pass_count            integer,
    wf_ic_sharpe             double precision,
    passes_walkforward       boolean,
    ic_sharpe                double precision,
    ic_sharpe_n_windows      integer,
    regime_label_source      text             NOT NULL DEFAULT 'none',
    computed_at              timestamptz      NOT NULL DEFAULT now(),
    ic_sortino               double precision,
    ic_win_rate              double precision,
    cluster_id               smallint,
    feature_status_at_eval   text             NOT NULL DEFAULT 'unknown',
    ic_sharpe_hac            double precision,
    regime_scope             text             NOT NULL,
    ic_shrunk                double precision,
    shrinkage_weight         double precision,
    partial_ic               double precision,
    partial_ic_p_value       double precision,
    partial_ic_n             integer,
    passes_partial_fdr       boolean,
    sign_hit_rate            double precision,
    magnitude_conditional_ic double precision,
    cumulative_e_value       double precision,
    CONSTRAINT feature_ic_scores_v2_pkey
        PRIMARY KEY (feature_name, symbol, tf, regime_scope, regime, lookahead_bars,
                     training_window_end),
    CONSTRAINT feature_ic_scores_v2_regime_scope_chk
        CHECK (regime_scope = ANY (ARRAY['unstratified', 'regime_volatility', 'member_window'])),
    CONSTRAINT feature_ic_scores_v2_fresh_scope_pooled_chk
        CHECK (is_pooled AND symbol = 'POOLED'),
    CONSTRAINT feature_ic_scores_v2_shrinkage_weight_unit_interval_chk
        CHECK (shrinkage_weight IS NULL OR (shrinkage_weight >= 0 AND shrinkage_weight <= 1))
);

SELECT create_hypertable(
    'feature_ic_scores_v2',
    'training_window_end',
    chunk_time_interval => INTERVAL '30 days'
);

ALTER TABLE feature_ic_scores_v2 SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol,tf',
    timescaledb.compress_orderby = 'training_window_end DESC'
);

COMMENT ON TABLE feature_ic_scores_v2 IS
    'Fresh IC scores (phase 186, migration 413): regime_scope is in the primary key. Sole writer services/ic_measure.py via bulk_load(). The legacy feature_ic_scores table is frozen and dropped whole by plan 186-28.';

COMMENT ON COLUMN feature_ic_scores_v2.training_window_end IS
    'The latest target exit bar used by the cell, always strictly before alpha.validation.oos_start. The only meaning this column carries in this table.';

COMMENT ON COLUMN feature_ic_scores_v2.regime_scope IS
    'One of unstratified (proposer cells, regime _all), regime_volatility (disclosure, regime = the label), member_window (monitoring, one row per window, regime _all).';

COMMIT;
