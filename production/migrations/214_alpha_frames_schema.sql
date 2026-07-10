-- Migration 214: alpha_frames hypertable + alpha.frame.*/alpha.scoring.*/infra.* APR seeds
-- (Phase 142B, FRAME-01)
--
-- Creates the alpha_frames table (FRAME-01) that AlphaFrameWriter writes to: one hypothetical
-- stop/target/hold position per alpha_events row, later scored by CounterfactualTracker
-- (Plan 02) as it observes the price path.
--
-- Governing DDL is docs/plans/2026-06-25-v30-alpha-lifecycle-schema.md (lines 122-193), with
-- FOUR deviations from that doc's literal SQL, each documented inline below:
--   (1) status CHECK constraint corrected per D-04 (the reversal-triggered close state is
--       dropped entirely, closed_ic_decay added) -- ROADMAP.md's FRAME-02/03 (2026-07-03,
--       later) supersedes the schema doc on this one point only.
--   (2) corpus_run_id / weight_epoch provenance columns added (Pitfall 6, canonical-simulator
--       provenance requirement).
--   (3) Identity/partitioning strategy corrected per cross-AI review finding H1: the schema
--       doc's sole-uuid-column primary key is INCOMPATIBLE with `create_hypertable('alpha_frames',
--       'bar_ts')` -- TimescaleDB requires every unique index, including the PK, to contain the
--       partitioning column. frame_id is declared `text NOT NULL` (deterministic content_key
--       hex string, not a uuid) and the PK is the COMPOSITE `PRIMARY KEY (frame_id, bar_ts)`.
--       `uq_alpha_frames_variant UNIQUE (event_id, bar_ts, frame_variant)` remains the
--       idempotency / ON CONFLICT target (already contains bar_ts, hypertable-valid).
--   (4) NO FOREIGN KEY to alpha_events (review M1). alpha_events is a hypertable TRUNCATEd on
--       every corpus rebuild by infrastructure_truncate_derived_tables.sh; an FK would either
--       block that TRUNCATE or (with CASCADE) silently wipe every frame, and a new
--       weight_version orphans old frames' parentage regardless -- referential integrity adds
--       fragility without value here. Provenance is instead carried by corpus_run_id and
--       weight_epoch (this project's data-retention / anti-join-checkpoint design does not
--       require an enforced FK). The truncate script is updated in this same migration's
--       companion task to TRUNCATE alpha_frames alongside alpha_events, the operational
--       substitute for the FK-CASCADE this deviation deliberately omits.
--
-- All statements idempotent: CREATE TABLE IF NOT EXISTS, ON CONFLICT DO NOTHING. Safe to re-run.

BEGIN;

-- -------------------------------------------------------------------------
-- Section 1: alpha_frames hypertable
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS alpha_frames (
    frame_id             text        NOT NULL,   -- BaseBatch.content_key(event_id, bar_ts, frame_variant); deterministic, not a uuid (review H1)
    event_id             text        NOT NULL,
    bar_ts               timestamptz NOT NULL,
    symbol               text        NOT NULL,
    tf                   text        NOT NULL,
    regime               text,
    direction            text        NOT NULL CHECK (direction IN ('long', 'short')),

    -- Frame variant identifier -- one row per (alpha_event, stop_atr_mult variant).
    -- 'primary' = current APR stop_atr_mult. This phase writes 'primary' only (the 4-variant
    -- calibration grid is explicitly out of scope -- CONTEXT.md "Out of scope").
    frame_variant        text        NOT NULL DEFAULT 'primary',

    -- Snapshot of alpha signal at frame creation (avoid re-joining alpha_events)
    alpha_score          double precision NOT NULL,
    alpha_ci_lower       double precision,
    alpha_ci_upper       double precision,

    -- D-03 diagnostic expected-R snapshot triad -- populated non-NULL at frame-creation time
    -- via compute_expected_r_snapshot(); reporting-only, never a gate input (see FRAME-04 /
    -- SHADOW-REVIEW.md D-01/D-02). Units documented below (review M5).
    gross_expected_r     double precision,
    net_expected_r       double precision,
    cost_r               double precision,

    -- Frame geometry (populated by CounterfactualTracker at T+1 bar open, Plan 02). NULL at
    -- FRAME-01 write time -- entry_price and a price-unit ATR are not known until the tracker
    -- observes the T+1 open (review H2: the ATR is caller-supplied to compute_frame_geometry,
    -- computed from market_data_ohlcv, never read from feature_vectors).
    entry_price          double precision,
    stop_price            double precision,
    target_price          double precision,
    r_multiple             double precision,  -- (target_price - entry_price) / (entry_price - stop_price)
    max_hold_bars        int,                -- APR snapshot at creation: alpha.frame.hold_max_bars.<regime>.<tf>
    stop_atr_mult         double precision,   -- APR snapshot at creation: alpha.frame.stop_atr_mult

    -- Lifecycle state machine (D-04 -- corrected from the 2026-06-25 schema doc):
    -- open -> closed_stop | closed_target | closed_max_hold | closed_ic_decay
    -- The prior schema doc's reversal-triggered close state is DROPPED entirely (bar-level
    -- alpha-sign reversal is noise at intraday resolution and destroys returns via excessive
    -- turnover -- ROADMAP.md FRAME-02/03 rationale). closed_ic_decay is the correct
    -- signal-based early exit trigger instead.
    status                text        NOT NULL DEFAULT 'open'
                              CHECK (status IN (
                                  'open',
                                  'closed_stop',
                                  'closed_target',
                                  'closed_max_hold',
                                  'closed_ic_decay'
                              )),

    -- Counterfactual outcome (written by CounterfactualTracker, Plan 02)
    counterfactual_pnl_r  double precision,
    counterfactual_mfe    double precision,
    counterfactual_mae    double precision,
    counterfactual_bars   int,
    exit_reason           text,
    closed_at             timestamptz,
    measured_at           timestamptz,    -- last CounterfactualTracker scan

    -- Provenance (Pitfall 6 / platform-canonical-simulator.md Open Question 3). Neither concept
    -- pre-existed in code; weight_epoch is a copy-through of alpha_events.weight_version,
    -- corpus_run_id is a fresh identifier pinned once per AlphaFrameWriter invocation.
    corpus_run_id         text,
    weight_epoch          text,

    created_at            timestamptz NOT NULL DEFAULT now(),

    -- Composite PK containing the partition column bar_ts (review H1 -- TimescaleDB requires
    -- every unique index, including the PK, to contain the hypertable's partitioning column).
    PRIMARY KEY (frame_id, bar_ts),

    -- Idempotency / ON CONFLICT target. Already contains bar_ts, so it is hypertable-valid.
    CONSTRAINT uq_alpha_frames_variant
        UNIQUE (event_id, bar_ts, frame_variant)

    -- NO FOREIGN KEY to alpha_events (review M1) -- see migration header deviation (4).
);

SELECT create_hypertable('alpha_frames', 'bar_ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS alpha_frames_status_open_idx
    ON alpha_frames (symbol, tf, bar_ts DESC)
    WHERE status = 'open';

CREATE INDEX IF NOT EXISTS alpha_frames_symbol_tf_idx
    ON alpha_frames (symbol, tf, bar_ts DESC);

CREATE INDEX IF NOT EXISTS alpha_frames_labeled_idx
    ON alpha_frames (bar_ts DESC, counterfactual_pnl_r)
    WHERE counterfactual_pnl_r IS NOT NULL AND frame_variant = 'primary';

-- D-03 unit documentation (review M5) -- a diagnostic magnitude nobody should confuse with
-- realized P&L (counterfactual_pnl_r, scored by Plan 02) or a probability.
COMMENT ON COLUMN alpha_frames.gross_expected_r IS
    'D-03 diagnostic snapshot, NOT a gate input. Ex-ante expected payoff MAGNITUDE in R at '
    'frame-entry time: abs(alpha_score) * alpha.frame.target_r_multiple. alpha_score is an '
    'IC-weighted ensemble score, not a probability; this is a directional-confidence magnitude '
    'scaled by the frame''s design R-multiple on a win, not a realized or expected P&L. '
    'Direction-agnostic (abs value) -- the traded direction is already fixed by the direction '
    'column. Reporting-only; SHADOW-REVIEW.md gates on realized counterfactual_pnl_r, never on '
    'this column.';

COMMENT ON COLUMN alpha_frames.cost_r IS
    'D-03 diagnostic snapshot. Per-row cost hurdle in return space, copied through from '
    'alpha_events.cost_hurdle (the audit snapshot alpha_publisher.py stamps at publish time via '
    '_cost_hurdle_for_tf) -- NOT re-derived live from the alpha.quant.cost_hurdle.<tf> APR key, '
    'so net_expected_r never silently drifts from historical truth on the next cost-hurdle '
    'recalibration + backfill re-run.';

COMMENT ON COLUMN alpha_frames.net_expected_r IS
    'D-03 diagnostic snapshot, NOT a gate input (D-01: SHADOW-REVIEW.md gates on GROSS '
    'counterfactual_pnl_r only). gross_expected_r - cost_r. D-02: reported as a mandatory '
    'REPORTING-ONLY column alongside every gross metric SHADOW-REVIEW.md commits to.';

-- -------------------------------------------------------------------------
-- Section 2: alpha.frame.* / alpha.scoring.* / infra.* APR seeds (9 new keys)
-- Does NOT re-seed the 36 existing alpha.frame.hold_max_bars.<regime>.<tf> keys (migration
-- 195/142A). Does NOT seed alpha.frame.grid_stop_atr_mults (4-variant grid, out of scope).
-- -------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES
(
    'alpha.frame.stop_atr_mult',
    'float',
    '1.5',
    '[initial_estimate] FRAME-01: stop-loss distance in ATR multiples from entry. '
    'Snapshotted onto every alpha_frames row at creation time. NOT an ML learning target.'
),
(
    'alpha.frame.target_r_multiple',
    'float',
    '2.0',
    '[initial_estimate] FRAME-01: target R-multiple (reward:risk ratio) applied on top of the '
    'ATR-derived stop distance -- target_price = entry +/- target_r_multiple * stop_distance. '
    'Use this exact key name (Pitfall 3) -- the ATR path is the sole target path '
    '(sr_resist_dist is 100% NULL across the corpus), so a conditional-fallback-style name '
    'would be inaccurate. NOT an ML learning target.'
),
(
    'alpha.frame.atr_period',
    'int',
    '14',
    '[conventional] FRAME-01: trailing bar count for the price-unit ATR that Plan 02''s '
    'CounterfactualTracker computes from market_data_ohlcv for frame geometry (review H2 -- '
    'feature_vectors has no price-unit ATR column, only normalized derivatives). '
    'NOT an ML learning target.'
),
(
    'alpha.scoring.min_strategy_n',
    'int',
    '30',
    '[conventional] FRAME-04: minimum closed-frame count per (tf, regime) cell required before '
    'the bootstrap exit gate evaluates that cell. Seeded here (not deferred to Phase 144) '
    'because FRAME-04, this phase''s own gate, reads it directly (Pitfall 4). '
    'NOT an ML learning target.'
),
(
    'alpha.scoring.bootstrap_max_n',
    'int',
    '5000',
    '[conventional] FRAME-04: day-cluster count ceiling above which the bootstrap gate uses an '
    'analytic one-sided CLT lower bound instead of scipy.stats.bootstrap(method=''BCa'') -- '
    'BCa''s bias-correction jackknife is both unnecessary and computationally infeasible at '
    'high cluster counts (review H4). NOT an ML learning target.'
),
(
    'alpha.scoring.bootstrap_batch',
    'int',
    '1000',
    '[conventional] FRAME-04: scipy.stats.bootstrap batch= parameter, caps peak resample matrix '
    'memory during the BCa bootstrap CI (review H4). NOT an ML learning target.'
),
(
    'infra.alpha_frame_writer.chunk_size',
    'int',
    '50000',
    '[conventional] AlphaFrameWriter: accumulate-and-flush chunk size for the per-(symbol,tf) '
    'anti-join write pass (Pattern 2 / D-05). Matches alpha_publisher.py''s _CHUNK_SIZE '
    'precedent. NOT an ML learning target.'
),
(
    'infra.counterfactual_tracker.itersize',
    'int',
    '5000',
    '[conventional] CounterfactualTracker (Plan 02): psycopg2 named server-side cursor itersize '
    'for the per-symbol bar-path scan. Matches ensemble_ic_engine.py''s pooled-fetch itersize '
    'precedent (migration 209). NOT an ML learning target.'
),
(
    'infra.counterfactual_tracker.workers',
    'int',
    '12',
    '[conventional] CounterfactualTracker (Plan 02): ProcessPoolExecutor worker count, one task '
    'per symbol. Matches infra.ic_engine.workers / infra.ensemble_ic_engine.workers precedent. '
    'NOT an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
('alpha.frame.stop_atr_mult',              '1.5',   1),
('alpha.frame.target_r_multiple',          '2.0',   1),
('alpha.frame.atr_period',                 '14',    1),
('alpha.scoring.min_strategy_n',           '30',    1),
('alpha.scoring.bootstrap_max_n',          '5000',  1),
('alpha.scoring.bootstrap_batch',          '1000',  1),
('infra.alpha_frame_writer.chunk_size',    '50000', 1),
('infra.counterfactual_tracker.itersize',  '5000',  1),
('infra.counterfactual_tracker.workers',   '12',    1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
(NOW(), 'alpha.frame.stop_atr_mult',             1, '1.5',   'migration_214', 'Initial estimate: FRAME-01 stop distance in ATR multiples [initial_estimate]'),
(NOW(), 'alpha.frame.target_r_multiple',         1, '2.0',   'migration_214', 'Initial estimate: FRAME-01 target R-multiple, ATR-only path (Pitfall 3 name resolution) [initial_estimate]'),
(NOW(), 'alpha.frame.atr_period',                1, '14',    'migration_214', 'Conventional: trailing ATR bar count for Plan 02 geometry fill [conventional]'),
(NOW(), 'alpha.scoring.min_strategy_n',          1, '30',    'migration_214', 'Conventional: FRAME-04 N-sufficiency floor, seeded here per Pitfall 4 [conventional]'),
(NOW(), 'alpha.scoring.bootstrap_max_n',         1, '5000',  'migration_214', 'Conventional: FRAME-04 BCa-vs-CLT method-selection ceiling, review H4 [conventional]'),
(NOW(), 'alpha.scoring.bootstrap_batch',         1, '1000',  'migration_214', 'Conventional: scipy.stats.bootstrap batch= memory cap, review H4 [conventional]'),
(NOW(), 'infra.alpha_frame_writer.chunk_size',   1, '50000', 'migration_214', 'Conventional: matches alpha_publisher.py chunk-size precedent [conventional]'),
(NOW(), 'infra.counterfactual_tracker.itersize', 1, '5000',  'migration_214', 'Conventional: matches ensemble_ic_engine.py pooled-fetch itersize precedent [conventional]'),
(NOW(), 'infra.counterfactual_tracker.workers',  1, '12',    'migration_214', 'Conventional: matches infra.ic_engine.workers / infra.ensemble_ic_engine.workers precedent [conventional]');

COMMIT;
