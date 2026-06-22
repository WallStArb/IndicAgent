-- Migration 160: IC engine tables — forward_returns and feature_ic_scores.
--
-- forward_returns:    Executable log returns per (symbol, tf, bar_ts). TimescaleDB
--                     hypertable partitioned by bar_ts (3-month chunks). Populated
--                     by the ForwardReturnWriter oneshot (Phase 138 P3).
--
-- feature_ic_scores:  Spearman IC results per (feature, symbol, tf, regime, lookahead,
--                     training_window_end). Populated by the ICEngine oneshot (P4).
--
-- Key design choice: is_pooled BOOLEAN (NOT NULL DEFAULT false) explicitly tags pooled
-- IC rows instead of relying on NULL regime. NULL uniqueness in Postgres is unreliable
-- for ON CONFLICT semantics — two rows with regime IS NULL are treated as distinct by
-- the PK, which would allow duplicate pooled rows to accumulate. The is_pooled flag
-- enables two precise partial unique indexes:
--
--   feature_ic_scores_pooled_uq  — for pooled runs (is_pooled=true, regime=NULL)
--   feature_ic_scores_regime_uq  — for regime-stratified runs (is_pooled=false, regime IS NOT NULL)
--
-- ON CONFLICT target:
--   Pooled rows:  DO UPDATE ... WHERE is_pooled = true  (targets pooled_uq)
--   Regime rows:  DO UPDATE ... WHERE is_pooled = false  (targets regime_uq)
-- Never rely on NULL uniqueness in Postgres.
--
-- All statements idempotent: CREATE TABLE IF NOT EXISTS, CREATE INDEX IF NOT EXISTS.
-- Safe to re-run.

-- -------------------------------------------------------------------------
-- Section 1: forward_returns
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS forward_returns (
    symbol                  text             NOT NULL,
    tf                      text             NOT NULL,
    bar_ts                  timestamptz      NOT NULL,   -- ts of the observation bar
    pipeline_version        text             NOT NULL,
    regime_label_source     text             NOT NULL DEFAULT 'filtered',
    -- Executable log returns: ln(open[T+N+1] / open[T+1])
    return_1bar             double precision,
    return_5bar             double precision,
    return_20bar            double precision,
    return_60bar            double precision,
    -- Completeness flags: false when LEAD() produced NULL (gap or end of data)
    complete_1bar           boolean          NOT NULL DEFAULT false,
    complete_5bar           boolean          NOT NULL DEFAULT false,
    complete_20bar          boolean          NOT NULL DEFAULT false,
    complete_60bar          boolean          NOT NULL DEFAULT false,
    -- Gap flag: true when a market-hours gap exists before the entry bar (T+1)
    has_gap_before_entry    boolean          NOT NULL DEFAULT false,
    computed_at             timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, tf, bar_ts)
);

SELECT create_hypertable(
    'forward_returns',
    'bar_ts',
    chunk_time_interval => INTERVAL '3 months',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS forward_returns_symbol_tf_ts_idx
    ON forward_returns (symbol, tf, bar_ts);

-- -------------------------------------------------------------------------
-- Section 2: feature_ic_scores
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS feature_ic_scores (
    feature_name            text             NOT NULL,
    vector_domain           text             NOT NULL,   -- 'quant' | 'micro' | 'macro' | 'calendar'
    symbol                  text             NOT NULL,
    tf                      text             NOT NULL,
    regime                  text,                        -- NULL when is_pooled=true
    lookahead_bars          int              NOT NULL,
    training_window_end     timestamptz      NOT NULL,   -- IC measured on data up to this date
    -- Pooled vs regime-stratified disambiguation (avoids NULL uniqueness ambiguity)
    -- is_pooled=true  → pooled cross-regime IC run; regime must be NULL
    -- is_pooled=false → regime-stratified run; regime must be non-NULL
    is_pooled               boolean          NOT NULL DEFAULT false,
    -- Sample information
    n_independent           int              NOT NULL,   -- sub-sampled observation count
    reliable                boolean          NOT NULL,   -- true if n_independent >= alpha.ic.min_reliable_n
    -- IC point estimate
    ic_value                double precision,
    ic_sign                 smallint,                    -- +1 or -1
    p_value                 double precision,
    -- Bootstrap CI
    ic_ci_lower             double precision,
    ic_ci_upper             double precision,
    passes_ci_gate          boolean,                     -- ic_ci_lower > 0.0
    -- FDR correction (computed across full batch via BH procedure)
    bh_adjusted_p           double precision,
    passes_fdr              boolean,
    -- Walk-forward results
    wf_fold_count           int,
    wf_pass_count           int,                         -- folds where IC > 0
    wf_ic_sharpe            double precision,            -- IC Sharpe across WF folds
    passes_walkforward      boolean,
    -- IC Sharpe (rolling window computation; NULL if < alpha.ic.sharpe_min_windows windows)
    ic_sharpe               double precision,
    ic_sharpe_n_windows     int,
    -- Regime source tracking
    regime_label_source     text             NOT NULL DEFAULT 'filtered',
    -- Decay state (written by AlphaDecayMonitor on daily rolling IC runs)
    is_decaying             boolean          NOT NULL DEFAULT false,
    decay_detected_at       timestamptz,
    recovery_eligible_at    timestamptz,                 -- earliest timestamp new evidence evaluated
    -- Bookkeeping
    computed_at             timestamptz      NOT NULL DEFAULT now(),
    -- Primary key: Postgres treats each NULL regime as distinct, so this PK works for
    -- regime-stratified rows but NOT for pooled rows (where regime IS NULL, two rows
    -- with regime=NULL are not treated as conflicting by the PK). Use partial unique
    -- indexes below for deduplication.
    PRIMARY KEY (feature_name, symbol, tf, regime, lookahead_bars, training_window_end)
);

-- Unique index for pooled rows (is_pooled=true, regime=NULL).
-- Use this index as the ON CONFLICT target for pooled IC upserts.
CREATE UNIQUE INDEX IF NOT EXISTS feature_ic_scores_pooled_uq
    ON feature_ic_scores (feature_name, symbol, tf, lookahead_bars, training_window_end)
    WHERE is_pooled = true;

-- Unique index for regime-stratified rows (is_pooled=false, regime non-NULL).
-- Use this index as the ON CONFLICT target for regime-stratified IC upserts.
CREATE UNIQUE INDEX IF NOT EXISTS feature_ic_scores_regime_uq
    ON feature_ic_scores (feature_name, symbol, tf, regime, lookahead_bars, training_window_end)
    WHERE is_pooled = false AND regime IS NOT NULL;

-- Query indexes
CREATE INDEX IF NOT EXISTS feature_ic_scores_gate_idx
    ON feature_ic_scores (passes_walkforward, passes_fdr, symbol, tf);

CREATE INDEX IF NOT EXISTS feature_ic_scores_domain_idx
    ON feature_ic_scores (vector_domain, symbol, tf);
