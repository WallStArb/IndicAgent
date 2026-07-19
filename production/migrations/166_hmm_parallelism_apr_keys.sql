-- Migration 166: APR keys for HMM parallelism and observation enrichment.
--
-- Seeds worker counts for ProcessPoolExecutor parallelism (regime_writer, ic_engine)
-- and observation feature windows for the enriched 5D HMM observation vector.
-- Also updates feature.hmm.n_iter from 20 to 200 — 20 iterations is insufficient
-- for convergence on 470k-row series (produces "Model is not converging" warnings
-- on nearly every symbol/tf cell; 200 eliminates most of them).
--
-- infra.regime_writer.workers: 12 = min(24_cores // 2, 16). Half of physical cores
--   to leave headroom for DB, OTel collector, and live services. Each worker holds
--   one psycopg2 connection and is CPU-bound on GaussianHMM.fit().
--   Speedup: 58 symbols / 12 workers = ~5 rounds × 42 min/symbol = ~3.5h vs 40h serial.
-- infra.ic_engine.workers: same rationale.
-- feature.hmm.obs_momentum_window: N-bar window for cumulative-return momentum feature.
--   20 bars = one trading day at 5m; captures short-term directional drift separate
--   from the raw log_return dimension. [initial_estimate]
-- feature.hmm.obs_vol_of_vol_window: window for rolling std of realized_vol.
--   Stable regimes have stable vol; transitions have erratic vol. This is the primary
--   indicator of regime change that the 2D observation space could not express.
--   [initial_estimate]

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'infra.regime_writer.workers',
    'int',
    '12',
    1, 32,
    '[initial_estimate] Number of ProcessPoolExecutor workers for regime_writer.py symbol-level parallelism. Each worker opens its own psycopg2 connection. Default 12 = min(24_cores // 2, 16). Not an ML learning target.'
),
(
    'infra.ic_engine.workers',
    'int',
    '12',
    1, 32,
    '[initial_estimate] Number of ProcessPoolExecutor workers for ic_engine.py symbol-level parallelism. Each worker opens its own psycopg2 connection and derives its RNG seed deterministically from bootstrap_seed + hash(symbol). Not an ML learning target.'
),
(
    'feature.hmm.obs_momentum_window',
    'int',
    '20',
    5, 200,
    '[initial_estimate] N-bar window for the momentum observation feature in the 5D HMM observation vector. Computed as sum(log_returns[-N:]) / (realized_vol + eps), capturing directional drift normalized by vol. 20 bars = one trading day at 5m. Not an ML learning target.'
),
(
    'feature.hmm.obs_vol_of_vol_window',
    'int',
    '20',
    5, 200,
    '[initial_estimate] M-bar window for the vol-of-vol observation feature: rolling std of realized_vol. Stable regimes have stable realized_vol; transitions have erratic realized_vol. 20 bars = one trading day at 5m. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('infra.regime_writer.workers',       '12',  1),
('infra.ic_engine.workers',           '12',  1),
('feature.hmm.obs_momentum_window',   '20',  1),
('feature.hmm.obs_vol_of_vol_window', '20',  1)
ON CONFLICT (config_key) DO NOTHING;

-- Update n_iter: 20 → 200. The existing description mentioned 50 as standard;
-- 200 provides headroom for large series (470k rows at 5m) where EM convergence
-- is slow due to near-IID return distributions at short timeframes.
UPDATE config_state SET config_value = '200', version = version + 1
WHERE config_key = 'feature.hmm.n_iter';

UPDATE config_schema SET
    default_value = '200',
    description = '[conventional] Maximum Baum-Welch EM iterations for GaussianHMM training. 200 provides convergence headroom for 470k-row 5m series where the near-IID return distribution makes EM slow to converge. Not an ML learning target.'
WHERE config_key = 'feature.hmm.n_iter';
