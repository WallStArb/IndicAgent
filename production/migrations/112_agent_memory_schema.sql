-- Migration 112: Agent Memory Schema
-- Phase: 097 (Agent Memory)
-- Purpose: 6 custom pgvector tables, 3 ENUMs, all indexes, hypertables, and compression
--          policies for the pgvector-native memory substrate (Renaissance constraints C-01-C-04).
-- Date: 2026-06-02
--
-- Tables:
--   memory_system_state         -- single-row epoch registry
--   memory_episodes_raw         -- write-only from live pipeline; no HNSW index
--   memory_episodes_labeled     -- physical copy with resolved outcomes; HNSW index
--   memory_calibration_promoted -- offline-validated stats, N>=30 CHECK (C-03)
--   memory_calibration_spc      -- SPC timeseries for drift alerting (tier 8)
--   memory_regime_transitions   -- Markov state machine for regime priors (tier 5)
--
-- ENUMs:
--   memory_episode_kind  -- episodic | disagreement | relational
--   memory_regime_label  -- ranging | trending_up | trending_down
--   memory_spc_stat      -- 5 stat names for SPC rows
--
-- Idempotent: safe to re-run on a DB where migration has already been applied.
-- Requires: pgvector 0.8.2+ installed in TimescaleDB (already present).

BEGIN;

-- ---------------------------------------------------------------------------
-- 5.1 Support Table: memory_system_state
-- Single-row registry. Live pipeline reads current_regime_epoch at episode
-- insert time (C-01). Nightly batch job is the sole writer.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memory_system_state (
    id                   INTEGER     PRIMARY KEY DEFAULT 1,
    current_regime_epoch INTEGER     NOT NULL DEFAULT 1,
    epoch_updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT single_row CHECK (id = 1)
);

-- Seed exactly one row on first run; idempotent on re-run.
INSERT INTO memory_system_state DEFAULT VALUES ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 5.2 ENUMs
-- Guards use EXCEPTION WHEN duplicate_object so re-running does not error.
-- ---------------------------------------------------------------------------
DO $$ BEGIN
    CREATE TYPE memory_episode_kind AS ENUM ('episodic', 'disagreement', 'relational');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE memory_regime_label AS ENUM ('ranging', 'trending_up', 'trending_down');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE memory_spc_stat AS ENUM (
        'calibration_error', 'brier_score', 'skill_score',
        'information_coefficient', 'mean_prediction'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ---------------------------------------------------------------------------
-- 5.3 Episode Layer: Raw
-- Write-only from live pipeline. No HNSW index -- agents never query here.
-- outcome uses exact 9-value set from D-09 (signal_outcomes table).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memory_episodes_raw (
    id               UUID                NOT NULL DEFAULT gen_random_uuid(),
    ts               TIMESTAMPTZ         NOT NULL,
    written_at       TIMESTAMPTZ         NOT NULL DEFAULT NOW(),
    kind             memory_episode_kind NOT NULL,
    signal_id        UUID,
    symbol           TEXT                NOT NULL,
    timeframe        TEXT                NOT NULL,
    agent_id         TEXT,
    embedding        vector(768),                   -- async; NULL until EmbeddingWorker processes
    embedding_text   TEXT,                          -- serialized input; stored for audit + re-embedding
    hmm_regime       TEXT,
    vol_regime       TEXT,
    entry_type       TEXT,
    regime_epoch     INTEGER             NOT NULL,  -- C-01: from memory_system_state at insert time
    n_eligible       INTEGER,                       -- C-02: NULL at write; backfill job populates
    memory_assisted  BOOLEAN             NOT NULL DEFAULT FALSE,  -- C-04
    outcome          TEXT,
    CONSTRAINT chk_raw_outcome CHECK (
        outcome IS NULL OR outcome IN (
            'never_activated', 'stopped_at_entry', 'stopped_in_trade',
            'target_1', 'target_1_2', 'target_full',
            'ttl_expired_ahead', 'ttl_expired_behind', 'condition_expired'
        )
    ),
    pnl_r            FLOAT,
    -- payload structure by kind:
    --   episodic:     {failure_prob, confidence, agent_scores: {agent_id: value}}
    --   disagreement: {agent_id_a, agent_id_b, score_a, score_b, disagreement_delta}
    --   relational:   {related_symbols: [], co_regime_states: {symbol: regime}}
    payload          JSONB               NOT NULL DEFAULT '{}',
    PRIMARY KEY (id, ts)
);

SELECT create_hypertable('memory_episodes_raw', 'ts', if_not_exists => TRUE);

-- Back-fill job: episodes ready to label (signal resolved + embedding present)
CREATE INDEX IF NOT EXISTS mem_raw_ready_for_label ON memory_episodes_raw (signal_id, ts)
    WHERE outcome IS NULL AND signal_id IS NOT NULL AND embedding IS NOT NULL;
CREATE INDEX IF NOT EXISTS mem_raw_signal ON memory_episodes_raw (signal_id)
    WHERE signal_id IS NOT NULL AND outcome IS NULL;

-- ---------------------------------------------------------------------------
-- 5.4 Episode Layer: Labeled
-- Physical copy with resolved outcomes. Agents read ONLY from here.
-- embedding NOT NULL: backfill job filters embedding IS NOT NULL before copying.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memory_episodes_labeled (
    id               UUID                NOT NULL,
    ts               TIMESTAMPTZ         NOT NULL,
    written_at       TIMESTAMPTZ         NOT NULL,
    labeled_at       TIMESTAMPTZ         NOT NULL DEFAULT NOW(),
    kind             memory_episode_kind NOT NULL,
    signal_id        UUID                NOT NULL,
    symbol           TEXT                NOT NULL,
    timeframe        TEXT                NOT NULL,
    agent_id         TEXT,
    embedding        vector(768)         NOT NULL,  -- NOT NULL: backfill filters embedding IS NOT NULL
    embedding_text   TEXT                NOT NULL,
    hmm_regime       TEXT,
    vol_regime       TEXT,
    entry_type       TEXT,
    regime_epoch     INTEGER             NOT NULL,
    n_eligible       INTEGER,
    memory_assisted  BOOLEAN             NOT NULL DEFAULT FALSE,
    outcome          TEXT                NOT NULL,
    CONSTRAINT chk_labeled_outcome CHECK (
        outcome IN (
            'never_activated', 'stopped_at_entry', 'stopped_in_trade',
            'target_1', 'target_1_2', 'target_full',
            'ttl_expired_ahead', 'ttl_expired_behind', 'condition_expired'
        )
    ),
    pnl_r            FLOAT               NOT NULL,
    mae              FLOAT,
    mfe              FLOAT,
    bars_in_trade    INTEGER,
    payload          JSONB               NOT NULL DEFAULT '{}',
    PRIMARY KEY (id, ts)
);

SELECT create_hypertable('memory_episodes_labeled', 'ts', if_not_exists => TRUE);

-- MemoryClient.recall() hot path -- ef_search=100 required at query time (D-11)
CREATE INDEX IF NOT EXISTS mem_labeled_hnsw ON memory_episodes_labeled
    USING hnsw (embedding vector_cosine_ops) WITH (m = 32, ef_construction = 128);
CREATE INDEX IF NOT EXISTS mem_labeled_cohort ON memory_episodes_labeled
    (agent_id, symbol, hmm_regime, entry_type, regime_epoch) WHERE agent_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS mem_labeled_epoch ON memory_episodes_labeled (regime_epoch DESC, ts DESC);

ALTER TABLE memory_episodes_labeled SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol, hmm_regime',
    timescaledb.compress_orderby   = 'ts DESC'
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM timescaledb_information.jobs
        WHERE hypertable_name = 'memory_episodes_labeled'
          AND proc_name = 'policy_compression'
    ) THEN
        PERFORM add_compression_policy('memory_episodes_labeled', INTERVAL '30 days');
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 5.5 Calibration Layer: Promoted
-- Offline-validated stats. Agents read ONLY from here. Append-only.
-- C-03: CHECK (sample_n >= 30) enforced at the DB layer -- cannot be bypassed.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memory_calibration_promoted (
    id                          UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    promoted_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    agent_id                    TEXT        NOT NULL,
    symbol                      TEXT,
    hmm_regime                  TEXT,
    entry_type                  TEXT,
    regime_epoch                INTEGER     NOT NULL,
    window_start                TIMESTAMPTZ NOT NULL,
    window_end                  TIMESTAMPTZ NOT NULL,
    -- C-03: structural gate -- batch job cannot write below N=30
    sample_n                    INTEGER     NOT NULL,
    CONSTRAINT chk_cal_sample_n CHECK (sample_n >= 30),
    -- Core calibration
    mean_prediction             FLOAT       NOT NULL,
    actual_rate                 FLOAT       NOT NULL,
    calibration_error           FLOAT       NOT NULL,
    calibration_error_variance  FLOAT       NOT NULL,
    correction_factor           FLOAT,                -- NULL when not statistically significant
    correction_factor_stable    BOOLEAN     NOT NULL DEFAULT FALSE,
    -- Brier decomposition
    brier_score                 FLOAT       NOT NULL,
    base_rate                   FLOAT       NOT NULL,
    reliability_score           FLOAT       NOT NULL,
    resolution_score            FLOAT       NOT NULL,
    skill_score                 FLOAT       NOT NULL,  -- negative = worse than trivial predictor
    -- IC
    information_coefficient     FLOAT       NOT NULL,
    ic_t_stat                   FLOAT       NOT NULL,
    ic_p_value                  FLOAT       NOT NULL,
    -- Statistical significance (BH-FDR corrected; circular block bootstrap)
    ci_lower                    FLOAT       NOT NULL,
    ci_upper                    FLOAT       NOT NULL,
    bootstrap_block_length      INTEGER     NOT NULL,
    p_value_raw                 FLOAT       NOT NULL,
    p_value_corrected           FLOAT       NOT NULL,  -- Benjamini-Hochberg FDR
    n_hypotheses_tested         INTEGER     NOT NULL,
    -- C-02: selection bias
    n_eligible                  INTEGER,
    p_signal                    FLOAT,                 -- sample_n / n_eligible
    -- C-04: feedback loop
    memory_assisted_n           INTEGER     NOT NULL DEFAULT 0,
    memory_assisted_fraction    FLOAT       NOT NULL DEFAULT 0.0,
    feedback_loop_p             FLOAT,
    feedback_loop_quarantine    BOOLEAN     NOT NULL DEFAULT FALSE,
    quarantine_review_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS mem_cal_cohort_latest ON memory_calibration_promoted
    (agent_id, symbol, hmm_regime, entry_type, regime_epoch, promoted_at DESC)
    WHERE feedback_loop_quarantine = FALSE;
CREATE INDEX IF NOT EXISTS mem_cal_quarantine_review ON memory_calibration_promoted
    (quarantine_review_at) WHERE feedback_loop_quarantine = TRUE AND quarantine_review_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS mem_cal_skill ON memory_calibration_promoted
    (agent_id, regime_epoch, promoted_at DESC) WHERE skill_score < 0.0;
CREATE INDEX IF NOT EXISTS mem_cal_drift ON memory_calibration_promoted
    (agent_id, symbol, hmm_regime, entry_type, promoted_at ASC);

-- ---------------------------------------------------------------------------
-- 5.6 Calibration Layer: SPC Timeseries
-- Source data for promotion job and drift alerting. Agents never read this.
-- ewma_lambda stored per row -- UCL/LCL are uninterpretable without it.
-- cusum_h_sigma (in sigma units) + cusum_h_absolute both stored for cross-agent comparability.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memory_calibration_spc (
    ts               TIMESTAMPTZ      NOT NULL,
    agent_id         TEXT             NOT NULL,
    symbol           TEXT,
    hmm_regime       TEXT,
    entry_type       TEXT,
    regime_epoch     INTEGER          NOT NULL,
    stat_name        memory_spc_stat  NOT NULL,
    window_bars      INTEGER          NOT NULL,
    sample_n         INTEGER          NOT NULL,
    ewma_lambda      FLOAT            NOT NULL,   -- stored; UCL/LCL uninterpretable without it
    ewma_value       FLOAT            NOT NULL,
    ewma_stddev      FLOAT            NOT NULL,
    ewma_ucl         FLOAT            NOT NULL,
    ewma_lcl         FLOAT            NOT NULL,
    ewma_alarm       BOOLEAN          NOT NULL DEFAULT FALSE,
    cusum_pos        FLOAT            NOT NULL DEFAULT 0.0,
    cusum_neg        FLOAT            NOT NULL DEFAULT 0.0,
    cusum_h_sigma    FLOAT            NOT NULL,   -- threshold in sigma units (typically 5.0)
    cusum_h_absolute FLOAT            NOT NULL,
    cusum_alarm      BOOLEAN          NOT NULL DEFAULT FALSE,
    ks_stat          FLOAT,
    ks_p_value       FLOAT,
    ks_alarm         BOOLEAN          NOT NULL DEFAULT FALSE,
    PRIMARY KEY (ts, agent_id, stat_name)
);

SELECT create_hypertable('memory_calibration_spc', 'ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS mem_spc_alarms ON memory_calibration_spc (agent_id, stat_name, ts DESC)
    WHERE ewma_alarm = TRUE OR cusum_alarm = TRUE OR ks_alarm = TRUE;
CREATE INDEX IF NOT EXISTS mem_spc_cohort ON memory_calibration_spc
    (agent_id, symbol, hmm_regime, entry_type, stat_name, ts DESC);

ALTER TABLE memory_calibration_spc SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'agent_id, stat_name',
    timescaledb.compress_orderby   = 'ts DESC'
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM timescaledb_information.jobs
        WHERE hypertable_name = 'memory_calibration_spc'
          AND proc_name = 'policy_compression'
    ) THEN
        PERFORM add_compression_policy('memory_calibration_spc', INTERVAL '7 days');
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 5.7 Regime Transitions (Tier 5)
-- Markov state machine. UNIQUE INDEX WHERE ts_end IS NULL is the structural
-- guarantee of at most one open period per (symbol, timeframe) -- not app logic.
-- transition_probs CHECK ensures probabilities sum to 1.0 +/- 0.001.
-- win_rate NULL when signal_count < 30 (C-03 discipline on satellite table).
--
-- Note: Regular table (not hypertable) to preserve the UNIQUE INDEX WHERE ts_end IS NULL
-- semantics. TimescaleDB hypertables require the partition key in every UNIQUE index,
-- which would invalidate the single-open-period structural guarantee. This table is
-- low-volume (one row per regime period per symbol/timeframe) and does not need chunking.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memory_regime_transitions (
    id                   UUID                NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    ts_start             TIMESTAMPTZ         NOT NULL,
    ts_end               TIMESTAMPTZ,
    symbol               TEXT                NOT NULL,
    timeframe            TEXT                NOT NULL,
    regime_epoch         INTEGER             NOT NULL,
    from_regime          memory_regime_label,
    to_regime            memory_regime_label NOT NULL,
    duration_bars        INTEGER,
    duration_seconds     FLOAT,
    signal_count         INTEGER,
    win_count            INTEGER,
    win_rate             FLOAT,              -- NULL if signal_count < 30
    avg_pnl_r            FLOAT,
    avg_mae              FLOAT,
    avg_mfe              FLOAT,
    transition_probs     JSONB,              -- NULL if transition_n < 30
    transition_n         INTEGER,
    duration_median_bars INTEGER,
    duration_p25_bars    INTEGER,
    duration_p75_bars    INTEGER,
    CONSTRAINT chk_win_rate CHECK (win_rate IS NULL OR (win_rate >= 0.0 AND win_rate <= 1.0)),
    CONSTRAINT chk_transition_probs_sum CHECK (
        transition_probs IS NULL OR
        ABS((transition_probs->>'ranging')::float +
            (transition_probs->>'trending_up')::float +
            (transition_probs->>'trending_down')::float - 1.0) < 0.001
    )
);

-- Structural single-open-period guarantee: at most one row per (symbol, timeframe) with ts_end IS NULL
CREATE UNIQUE INDEX IF NOT EXISTS mem_reg_open ON memory_regime_transitions (symbol, timeframe)
    WHERE ts_end IS NULL;
CREATE INDEX IF NOT EXISTS mem_reg_history ON memory_regime_transitions
    (symbol, timeframe, ts_start DESC);
CREATE INDEX IF NOT EXISTS mem_reg_duration ON memory_regime_transitions
    (symbol, timeframe, to_regime, duration_bars) WHERE ts_end IS NOT NULL AND duration_bars IS NOT NULL;

COMMIT;
