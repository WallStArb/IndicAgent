-- Migration 410: HMM regime kernel APR cleanup and block-size key (phase 186 plan 186-13)
--
-- Walk-forward is the only HMM mode (D-29): the full-history single fit, its
-- `--walk-forward` switches and its held-out scoring are deleted from services/regime_writer.py.
-- Three APR keys have no reader left:
--   alpha.hmm.walk_forward.enabled  (migration 292): selected walk-forward over the single fit
--   alpha.hmm.n_restarts            (migration 277): multi-seed restarts of the single fit
--   feature.hmm.heldout_fraction    (migration 176): held-out log-likelihood of the single fit
-- The repo-wide grep recorded in 186-13-SUMMARY.md finds readers only in the analysis pilots
-- 186-16 deletes (scripts/analysis/hmm_*), which import the deleted function and no longer run.
-- config_history rows stay (the audit trail of every past value); config_state and
-- config_schema rows go. At deletion time the last history rows were: n_restarts 1
-- (migration_277 seed), heldout_fraction 0.2 (migration_179 seed), walk_forward.enabled true
-- (version 2, set by the operator on 2026-08-12 when the legacy column went walk-forward); no
-- row held a value that differed from what the code now does unconditionally. The per-tf alpha.hmm.walk_forward.refit_every_bars.* and
-- initial_warmup_bars.* keys stay: the kernels read them.
--
-- infra.hmm.rolling_block_rows: rows per block in the obs-builder rolling reductions
-- (kernels/_hmm.py `_rolling`). At 395,609 rows and window 250 the unblocked np.std allocates
-- about 810 MB per reduction (tracemalloc peak); blocked at 16384 rows the peak is about 49 MB.
-- The output is bit-identical at every block size (tests/unit/intelligence/test_regime_kernel.py).

BEGIN;

DELETE FROM config_state
WHERE config_key IN (
    'alpha.hmm.walk_forward.enabled',
    'alpha.hmm.n_restarts',
    'feature.hmm.heldout_fraction'
);

DELETE FROM config_schema
WHERE config_key IN (
    'alpha.hmm.walk_forward.enabled',
    'alpha.hmm.n_restarts',
    'feature.hmm.heldout_fraction'
);

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'infra.hmm.rolling_block_rows',
    'int',
    '16384',
    1, NULL,
    '[initial_estimate] rows per block in the HMM obs-builder rolling reductions; bounds '
    'transient memory, does not change output; not an ML target'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('infra.hmm.rolling_block_rows', '16384', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'infra.hmm.rolling_block_rows', 1, '16384', 'migration_410',
       'Initial value: about 32 MB of window intermediate at window 250 [initial_estimate]'
WHERE NOT EXISTS (
    SELECT 1 FROM config_history h
    WHERE h.config_key = 'infra.hmm.rolling_block_rows' AND h.changed_by = 'migration_410'
);

COMMIT;
