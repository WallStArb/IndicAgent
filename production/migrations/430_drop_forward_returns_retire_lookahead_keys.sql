-- Migration 430: drop the forward_returns table and retire the old IC stack's APR keys
-- (phase 186 plan 23, D-22 one-change deletion; D-08 per-key grep evidence).
--
-- forward_returns was the old ic_engine/forward_return_writer chain's target store
-- (hypertable, compression job 1066, ~14 GB). Its replacement was proven before this
-- drop: the committed parity evidence lives in
-- .planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-20-PARITY-REPORT.md
-- (table-target replay PASS, 1078/1080 exact + 2 float32-noise cells; writer-path cell
-- delta 0.0 at 1e-9), and phase 185 D-14 moved the bar-describing flags (gap_before_next,
-- return_magnitude) into bar flags (src/intelligence/bars/scrub_rules.py) before this
-- plan deleted the writer that used to originate them.
--
-- PRECONDITIONS ASSERTED BEFORE THIS MIGRATION WAS WRITTEN (186-23 Task 1, recorded in
-- 186-23-SUMMARY.md):
--   1. Zero non-idle foreign sessions touching forward_returns or feature_ic_scores
--      (pg_stat_activity query returned 0 rows immediately before the apply).
--   2. No live or resumable ic_engine / rebuild / corpus-pipeline process (ps, log
--      tails, STATE.md lane table, orchestrator pgrep all clear).
--   3. The 186-20 parity report is committed on main and carries a PASS writer-path cell.
--   4. feature_ic_scores (10,616,092 rows) and feature_vectors are NOT touched here;
--      186-27/186-28 own those.
--
-- Plain DROP TABLE removes the TimescaleDB compression job automatically (186-22
-- precedent). Nothing is decompressed by a plain drop, so no bare VACUUM is required
-- (D-16); tests/unit/test_compressed_hypertable_migration_vacuum_check.py proves the
-- migration satisfies the vacuum rule.
--
-- APR retirement (D-22/D-08: every key classified by a literal-key repo grep, recorded
-- in the summary; literal IN lists only, never LIKE; idempotent DELETEs):
--   DELETE (zero surviving runtime readers):
--     - alpha.ic.lookahead.{5m,15m,1h,1d}.{fast,mid,slow,extended} + the 4 base keys
--       (20): only readers were ic_engine, forward_return_writer, the ops scripts
--       deleted in the same change, and src/observability/corpus_manifest_verifier.py,
--       whose by-value mirror (equal bytewise at retirement, verified in Task 1) is now
--       the documented source of the expected per-tf grid.
--     - alpha.ensemble.cluster_regime_conditioned: only runtime reader was
--       services/ic_engine.py's cfg.get_sync (line ~840), deleted in the same change.
--     - alpha.ic.insert_batch_size: only reader was services/forward_return_writer.py.
--     - infra.ic_engine.* (16): only reader was services/ic_engine.py.
--     - infra.ensemble_ic_engine.{workers,pooled_fetch_itersize}: reader
--       (services/ensemble_ic_engine.py) deleted by 186-19; the keys were left behind;
--       the repo-wide grep in 186-23 Task 1 confirmed zero surviving readers.
--   KEEP (live readers verified in the same grep -- deliberately absent below):
--     - alpha.forward_returns.gap_max_seconds, alpha.forward_returns.gap_multiplier:
--       adopted by phase 185's bar-flag code (src/intelligence/bars/scrub_rules.py
--       reads both at runtime).
--     - alpha.quant.cross_symbol_corroboration.{min_symbols,window_minutes}: live
--       readers in src/intelligence/bars/scrub_rules.py, services/bar_auditor.py and
--       scripts/ops/corpus/ops_known_corrupt_print_cleanup.py.
--   KEEP elsewhere (not touched by this migration): alpha.ensemble.mv_condition_max
--   (services/tag_calibrator.py), alpha.ic.shrinkage_k (research lane),
--   alpha.ic.canary_rng_seed (feature_factory), alpha.ic.active_scales.{tf}, and every
--   alpha.ic.* key services/ic_measure.py reuses (subsample_min_stride,
--   bootstrap_block_size.*, bootstrap_resamples, bootstrap_seed, fdr_alpha,
--   min_observations, hac_max_lag, feature_block_columns, alpha.validation.oos_start).

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. GUARD -- refuse to drop while another session is reading the table.
-- ---------------------------------------------------------------------------

DO $$
DECLARE
    v_reader_pid INT;
BEGIN
    SELECT min(pid) INTO v_reader_pid
    FROM pg_stat_activity
    WHERE pid <> pg_backend_pid()
      AND state <> 'idle'
      AND query ILIKE '%forward_returns%';
    IF v_reader_pid IS NOT NULL THEN
        RAISE EXCEPTION 'refusing to drop: another session is reading forward_returns (pid %)', v_reader_pid;
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 2. DROP -- no IF EXISTS, no CASCADE: the table must exist and have no dependents.
-- ---------------------------------------------------------------------------

DROP TABLE forward_returns;

-- ---------------------------------------------------------------------------
-- 3. APR retirement -- literal per-key DELETEs from all three config tables.
-- ---------------------------------------------------------------------------

DELETE FROM config_history
 WHERE config_key IN (
    'alpha.ic.lookahead.fast', 'alpha.ic.lookahead.mid', 'alpha.ic.lookahead.slow', 'alpha.ic.lookahead.extended',
    'alpha.ic.lookahead.5m.fast', 'alpha.ic.lookahead.5m.mid', 'alpha.ic.lookahead.5m.slow', 'alpha.ic.lookahead.5m.extended',
    'alpha.ic.lookahead.15m.fast', 'alpha.ic.lookahead.15m.mid', 'alpha.ic.lookahead.15m.slow', 'alpha.ic.lookahead.15m.extended',
    'alpha.ic.lookahead.1h.fast', 'alpha.ic.lookahead.1h.mid', 'alpha.ic.lookahead.1h.slow', 'alpha.ic.lookahead.1h.extended',
    'alpha.ic.lookahead.1d.fast', 'alpha.ic.lookahead.1d.mid', 'alpha.ic.lookahead.1d.slow', 'alpha.ic.lookahead.1d.extended',
    'alpha.ensemble.cluster_regime_conditioned',
    'alpha.ic.insert_batch_size'
);

DELETE FROM config_state
 WHERE config_key IN (
    'alpha.ic.lookahead.fast', 'alpha.ic.lookahead.mid', 'alpha.ic.lookahead.slow', 'alpha.ic.lookahead.extended',
    'alpha.ic.lookahead.5m.fast', 'alpha.ic.lookahead.5m.mid', 'alpha.ic.lookahead.5m.slow', 'alpha.ic.lookahead.5m.extended',
    'alpha.ic.lookahead.15m.fast', 'alpha.ic.lookahead.15m.mid', 'alpha.ic.lookahead.15m.slow', 'alpha.ic.lookahead.15m.extended',
    'alpha.ic.lookahead.1h.fast', 'alpha.ic.lookahead.1h.mid', 'alpha.ic.lookahead.1h.slow', 'alpha.ic.lookahead.1h.extended',
    'alpha.ic.lookahead.1d.fast', 'alpha.ic.lookahead.1d.mid', 'alpha.ic.lookahead.1d.slow', 'alpha.ic.lookahead.1d.extended',
    'alpha.ensemble.cluster_regime_conditioned',
    'alpha.ic.insert_batch_size'
);

DELETE FROM config_schema
 WHERE config_key IN (
    'alpha.ic.lookahead.fast', 'alpha.ic.lookahead.mid', 'alpha.ic.lookahead.slow', 'alpha.ic.lookahead.extended',
    'alpha.ic.lookahead.5m.fast', 'alpha.ic.lookahead.5m.mid', 'alpha.ic.lookahead.5m.slow', 'alpha.ic.lookahead.5m.extended',
    'alpha.ic.lookahead.15m.fast', 'alpha.ic.lookahead.15m.mid', 'alpha.ic.lookahead.15m.slow', 'alpha.ic.lookahead.15m.extended',
    'alpha.ic.lookahead.1h.fast', 'alpha.ic.lookahead.1h.mid', 'alpha.ic.lookahead.1h.slow', 'alpha.ic.lookahead.1h.extended',
    'alpha.ic.lookahead.1d.fast', 'alpha.ic.lookahead.1d.mid', 'alpha.ic.lookahead.1d.slow', 'alpha.ic.lookahead.1d.extended',
    'alpha.ensemble.cluster_regime_conditioned',
    'alpha.ic.insert_batch_size'
);

DELETE FROM config_history
 WHERE config_key IN (
    'infra.ic_engine.corr_row_block',
    'infra.ic_engine.cross_sectional_bootstrap_threads',
    'infra.ic_engine.cs_chunk_ts',
    'infra.ic_engine.cs_fetch_connections',
    'infra.ic_engine.disk_backed_min_rows',
    'infra.ic_engine.memmap_scratch_dir',
    'infra.ic_engine.per_symbol_bootstrap_threads.15m',
    'infra.ic_engine.per_symbol_bootstrap_threads.1d',
    'infra.ic_engine.per_symbol_bootstrap_threads.1h',
    'infra.ic_engine.per_symbol_bootstrap_threads.5m',
    'infra.ic_engine.scratch_headroom_multiplier',
    'infra.ic_engine.scratch_min_free_after_fraction',
    'infra.ic_engine.symbol_fetch_chunk_rows',
    'infra.ic_engine.workers',
    'infra.ic_engine.x_nd_fill_block_rows',
    'infra.ensemble_ic_engine.workers',
    'infra.ensemble_ic_engine.pooled_fetch_itersize'
);

DELETE FROM config_state
 WHERE config_key IN (
    'infra.ic_engine.corr_row_block',
    'infra.ic_engine.cross_sectional_bootstrap_threads',
    'infra.ic_engine.cs_chunk_ts',
    'infra.ic_engine.cs_fetch_connections',
    'infra.ic_engine.disk_backed_min_rows',
    'infra.ic_engine.memmap_scratch_dir',
    'infra.ic_engine.per_symbol_bootstrap_threads.15m',
    'infra.ic_engine.per_symbol_bootstrap_threads.1d',
    'infra.ic_engine.per_symbol_bootstrap_threads.1h',
    'infra.ic_engine.per_symbol_bootstrap_threads.5m',
    'infra.ic_engine.scratch_headroom_multiplier',
    'infra.ic_engine.scratch_min_free_after_fraction',
    'infra.ic_engine.symbol_fetch_chunk_rows',
    'infra.ic_engine.workers',
    'infra.ic_engine.x_nd_fill_block_rows',
    'infra.ensemble_ic_engine.workers',
    'infra.ensemble_ic_engine.pooled_fetch_itersize'
);

DELETE FROM config_schema
 WHERE config_key IN (
    'infra.ic_engine.corr_row_block',
    'infra.ic_engine.cross_sectional_bootstrap_threads',
    'infra.ic_engine.cs_chunk_ts',
    'infra.ic_engine.cs_fetch_connections',
    'infra.ic_engine.disk_backed_min_rows',
    'infra.ic_engine.memmap_scratch_dir',
    'infra.ic_engine.per_symbol_bootstrap_threads.15m',
    'infra.ic_engine.per_symbol_bootstrap_threads.1d',
    'infra.ic_engine.per_symbol_bootstrap_threads.1h',
    'infra.ic_engine.per_symbol_bootstrap_threads.5m',
    'infra.ic_engine.scratch_headroom_multiplier',
    'infra.ic_engine.scratch_min_free_after_fraction',
    'infra.ic_engine.symbol_fetch_chunk_rows',
    'infra.ic_engine.workers',
    'infra.ic_engine.x_nd_fill_block_rows',
    'infra.ensemble_ic_engine.workers',
    'infra.ensemble_ic_engine.pooled_fetch_itersize'
);

COMMIT;
