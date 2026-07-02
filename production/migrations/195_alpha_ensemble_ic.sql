-- Migration 195: alpha_ensemble_ic hypertable + EIC-01/02/03 APR seeds (Phase 142A)
--
-- NOTE ON NUMBERING: PLAN 142A-01 specified this as migration 187. At execution time
-- 187-194 were already applied (187 itself was previously used and reverted for an
-- unrelated ensemble_weights demotion, per git history; 188/190-194 are live). This
-- migration is renumbered to 195 (next available) to avoid any collision. No content
-- change from the plan's intent -- see 142A-01-PLAN.md Task 1 for full rationale.
--
-- Creates the ensemble IC measurement table (EIC-01) that EnsembleICEngine writes to:
-- one row per (symbol, tf, regime, lookahead, scored_at) measuring
-- IC(alpha_score, forward_return_<lookahead>) using the same Fisher z-transform CI +
-- corpus-level BH-FDR + walk-forward machinery as the feature IC engine (ic_engine.py).
--
-- scored_at semantics (D-142A-R2): the service pins ONE run_ts = datetime.now(UTC) per
-- invocation and stamps every row's scored_at with that value. DEFAULT now() below is
-- only a safety net for ad-hoc manual inserts -- the service never relies on it. Because
-- scored_at is part of the composite PK, a within-run retry upserts in place via
-- ON CONFLICT (event_row_id, scored_at) DO UPDATE, while separate invocations accumulate
-- distinct IC vintages (mirrors ic_engine.computed_at design).
--
-- Regime namespace (OQ-1 resolution): uses the 9 LIVE cross-sectional market_regimes
-- labels ({low,mid,high}_{bull,neutral,bear}), NOT the stale 4-label bull/bear/sideways/
-- volatile set from the 2026-06-25 schema doc.
--
-- All statements idempotent: CREATE TABLE IF NOT EXISTS, ON CONFLICT DO NOTHING.
-- Safe to re-run.

BEGIN;

-- -------------------------------------------------------------------------
-- Section 1: alpha_ensemble_ic hypertable
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS alpha_ensemble_ic (
    event_row_id        text             NOT NULL,   -- BaseBatch.content_key(symbol, tf, regime, lookahead)
    symbol              text             NOT NULL,   -- 'POOLED' for cross-sectional rows, else ticker
    tf                  text             NOT NULL,
    regime              text             NOT NULL,   -- 9 cross-sectional labels {low,mid,high}_{bull,neutral,bear}
    lookahead           text             NOT NULL,   -- 'fast'|'mid'|'slow'|'extended'
    lookahead_bars      integer          NOT NULL,
    is_pooled           boolean          NOT NULL DEFAULT false,
    n_independent       integer,
    reliable            boolean,
    ic_value            double precision,
    ic_ci_lower         double precision,
    ic_ci_upper         double precision,
    ic_sharpe           double precision,
    ic_sharpe_hac       double precision,
    bh_adjusted_p       double precision,
    passes_fdr          boolean,
    walk_forward_stable boolean,                     -- EIC-03: fold IC-magnitude max/min ratio < wf_stability_ratio (D-142A-R1)
    -- scored_at: per-run vintage; service pins one run_ts=now(UTC) for the whole run (D-142A-R2).
    -- Part of PK so a retried run upserts in place; separate runs accumulate vintages.
    scored_at           timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (event_row_id, scored_at),
    -- Single source of truth for the pooled/per-symbol distinction -- a worker bug can
    -- never write a row where symbol='POOLED' and is_pooled disagree (review finding).
    CONSTRAINT alpha_ensemble_ic_pooled_symbol_consistent CHECK ((symbol = 'POOLED') = is_pooled)
);

SELECT create_hypertable(
    'alpha_ensemble_ic',
    'scored_at',
    chunk_time_interval => INTERVAL '3 months',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS alpha_ensemble_ic_cell_idx
    ON alpha_ensemble_ic (symbol, tf, regime, lookahead, scored_at DESC);

-- -------------------------------------------------------------------------
-- Section 2: alpha.ensemble_ic.* + infra.ensemble_ic_engine.* APR seeds (7 keys)
-- -------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES
(
    'alpha.ensemble_ic.decay_threshold',
    'float',
    '0.1',
    '[initial_estimate] EIC-02: IC Sharpe below this threshold marks the lookahead scale '
    'where ensemble alpha edge has decayed/expired for a (symbol, tf, regime) cell. Used '
    'to derive alpha.frame.hold_max_bars.<regime>.<tf> from the empirical IC decay curve '
    'after the first EnsembleICEngine run. Recalibrate once real decay curves exist. '
    'NOT an ML learning target.'
),
(
    'alpha.ensemble_ic.min_qualifying_fraction',
    'float',
    '0.60',
    '[initial_estimate] EIC-04 phase gate: minimum fraction of (symbol, tf, regime) cells '
    'that must satisfy ic_ci_lower > 0 AND passes_fdr = true (at gate_lookahead) on '
    'in-sample data before Phase 142B (frame simulation) begins. Renaissance correction: '
    '0.60 is an initial estimate, not a derived value -- recalibrate after the first run '
    'reveals how many cells have sufficient N. Never bake this fraction into gate code; '
    'always read from config_state. NOT an ML learning target.'
),
(
    'alpha.ensemble_ic.wf_stability_ratio',
    'float',
    '3.0',
    '[initial_estimate] EIC-03: walk_forward_stable = true when '
    'max(|fold_ic|) / min(|fold_ic|) < this ratio across the walk-forward folds. '
    'D-142A-R1: this is a fold IC-MAGNITUDE ratio, not a fold IC-Sharpe ratio -- a '
    'reliable per-fold Sharpe requires sharpe_min_windows(30) x sharpe_window_size(2000) '
    '= 60,000 bars inside one fold test slice, far above per-cell per-fold N. Matches '
    'ic_engine.py''s own fold-IC-scalar walk-forward gate. NOT an ML learning target.'
),
(
    'alpha.ensemble_ic.gate_lookahead',
    'str',
    'fast',
    '[initial_estimate] EIC-04: which lookahead scale (fast|mid|slow|extended) the phase '
    'gate evaluates min_qualifying_fraction against. fast = shortest holding horizon, '
    'most conservative initial gate. NOT an ML learning target.'
),
(
    'alpha.ensemble_ic.wf_stability_metric',
    'str',
    'ic_ratio',
    '[initial_estimate] EIC-03 stability metric. ''ic_ratio'' = fold IC-magnitude max/min '
    'ratio (v1 default, D-142A-R1: per-fold N << the 60k-bar floor a per-fold IC Sharpe '
    'needs). Swappable to ''ic_sharpe_ratio'' without a migration if cell N ever supports it.'
),
(
    'alpha.ensemble_ic.min_obs_per_regime',
    'int',
    '3000',
    '[initial_estimate] EIC-05 diagnosis threshold: per-(symbol, tf, regime) observation '
    'count below which a cell is flagged as data-starved (not signal-absent) during '
    'gate-failure diagnosis. Mirrors alpha.ic.min_obs_per_regime (migration 182) so the '
    'ensemble-level diagnosis uses the same data-sufficiency bar as the feature IC engine. '
    'NOT an ML learning target.'
),
(
    'infra.ensemble_ic_engine.workers',
    'int',
    '12',
    '[conventional] ProcessPoolExecutor worker count for EnsembleICEngine, one task per '
    '(symbol, tf). Matches infra.ic_engine.workers precedent (migration 169). '
    'NOT an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
('alpha.ensemble_ic.decay_threshold',        '0.1',       1),
('alpha.ensemble_ic.min_qualifying_fraction','0.60',      1),
('alpha.ensemble_ic.wf_stability_ratio',     '3.0',       1),
('alpha.ensemble_ic.gate_lookahead',         'fast',      1),
('alpha.ensemble_ic.wf_stability_metric',    'ic_ratio',  1),
('alpha.ensemble_ic.min_obs_per_regime',     '3000',      1),
('infra.ensemble_ic_engine.workers',         '12',        1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
(NOW(), 'alpha.ensemble_ic.decay_threshold',         1, '0.1',      'migration_195', 'Initial estimate: EIC-02 IC decay threshold [initial_estimate]'),
(NOW(), 'alpha.ensemble_ic.min_qualifying_fraction', 1, '0.60',     'migration_195', 'Initial estimate: EIC-04 phase gate fraction, recalibrate post first run [initial_estimate]'),
(NOW(), 'alpha.ensemble_ic.wf_stability_ratio',      1, '3.0',      'migration_195', 'Initial estimate: EIC-03 walk-forward stability ratio [initial_estimate]'),
(NOW(), 'alpha.ensemble_ic.gate_lookahead',          1, 'fast',     'migration_195', 'Initial estimate: EIC-04 gate lookahead scale [initial_estimate]'),
(NOW(), 'alpha.ensemble_ic.wf_stability_metric',     1, 'ic_ratio', 'migration_195', 'Initial estimate: EIC-03 stability metric selector, D-142A-R1 [initial_estimate]'),
(NOW(), 'alpha.ensemble_ic.min_obs_per_regime',      1, '3000',     'migration_195', 'Initial estimate: mirrors alpha.ic.min_obs_per_regime [initial_estimate]'),
(NOW(), 'infra.ensemble_ic_engine.workers',          1, '12',       'migration_195', 'Conventional: matches infra.ic_engine.workers precedent [conventional]');

-- -------------------------------------------------------------------------
-- Section 3: alpha.frame.hold_max_bars.<regime>.<tf> APR seeds (36 keys)
-- 9 LIVE market_regimes.regime_label values x 4 TFs (OQ-1 resolution --
-- NOT the stale bull/bear/sideways/volatile namespace from the schema doc).
-- Seeded at 60 bars as a conservative [initial_estimate]; EIC-02 overwrites
-- with data-derived values after the first EnsembleICEngine run.
-- -------------------------------------------------------------------------

DO $$
DECLARE
    regimes text[] := ARRAY[
        'high_bear', 'high_bull', 'high_neutral',
        'low_bear', 'low_bull', 'low_neutral',
        'mid_bear', 'mid_bull', 'mid_neutral'
    ];
    tfs text[] := ARRAY['5m', '15m', '1h', '1d'];
    r text;
    t text;
    k text;
BEGIN
    FOREACH r IN ARRAY regimes LOOP
        FOREACH t IN ARRAY tfs LOOP
            k := 'alpha.frame.hold_max_bars.' || r || '.' || t;

            INSERT INTO config_schema (config_key, value_type, default_value, description)
            VALUES (
                k, 'int', '60',
                '[initial_estimate] max hold bars; overwritten by EIC-02 IC decay calibration. '
                'NOT an ML learning target. Regime=' || r || ', TF=' || t || '.'
            )
            ON CONFLICT (config_key) DO NOTHING;

            INSERT INTO config_state (config_key, config_value, version)
            VALUES (k, '60', 1)
            ON CONFLICT (config_key) DO NOTHING;

            INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
            VALUES (
                NOW(), k, 1, '60', 'migration_195',
                'Initial estimate: conservative hold_max_bars default pending EIC-02 calibration [initial_estimate]'
            );
        END LOOP;
    END LOOP;
END $$;

COMMIT;
