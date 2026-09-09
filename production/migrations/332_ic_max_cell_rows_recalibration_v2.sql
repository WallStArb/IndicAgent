-- Migration 332: alpha.ic.max_cell_rows recalibration v2 (todo 371 follow-up)
--
-- The 10,000,000 ceiling (raised to this value at some point after migration
-- 259 set it to 4,000,000) was hit for real 2026-09-08 18:11 UTC:
-- equity/5m/mid_neutral had grown to 10,165,584 rows -- 254 GB rows,
-- 165,584 rows (1.7%) over the ceiling -- a clean CellTooLargeError, not an
-- OOM. Same growth mechanism as migration 259's own recalibration: migration
-- 331 (2026-09-03) routed 49 previously-unrouted single-name equities into
-- cross-sectional measurement, growing every equity cell, mid_neutral (the
-- historically largest 5m equity regime, same cell 259 measured at ~3.0M
-- rows) now the largest by a wide margin.
--
-- This time sized from real, not synthetic, evidence: the SAME live recompute
-- run (relaunched 2026-09-07 with +96GB swap headroom after an unrelated OOM
-- on the even-larger equity/5m/high_bear cell) successfully completed
-- high_bear itself at ~64M rows -- proof this host, under its current swap
-- configuration, comfortably clears cells 6x the new ceiling below. mid_neutral
-- at 10.17M rows is nowhere near that proven envelope; the ceiling was simply
-- stale, not a real capacity constraint.
--
-- New ceiling: 15,000,000 -- ~1.5x mid_neutral's exact measured size (matching
-- migration 259's own ~1.33x margin-over-measured-largest practice), a small
-- fraction of the 64M-row envelope already proven survivable this same run.
-- Not raised further: todo 371 (the guard's post-materialization timing gap)
-- is still open and unfixed -- a much higher ceiling would just move the same
-- crash-loud/OOM-race question further out, not resolve it. This bump exists
-- to clear the one specific cell now blocking the run, not to preempt every
-- future one.

BEGIN;

UPDATE config_schema
SET max_value = 20000000
WHERE config_key = 'alpha.ic.max_cell_rows' AND max_value < 20000000;

UPDATE config_state
SET config_value = '15000000', version = version + 1, updated_at = NOW()
WHERE config_key = 'alpha.ic.max_cell_rows';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'alpha.ic.max_cell_rows', version, config_value, 'migration_332',
       'Recalibrated from 10,000,000 to 15,000,000 after equity/5m/mid_neutral grew to '
       '10,165,584 rows post-migration-331 regime-routing expansion, hitting the ceiling '
       'cleanly (CellTooLargeError, not OOM) 2026-09-08. Sized from real evidence: the '
       'same live run already completed the even-larger equity/5m/high_bear cell (~64M '
       'rows) successfully under its current +96GB swap configuration -- 15M is a small '
       'fraction of that proven-survivable envelope, not a stretch. todo 371 (the guard''s '
       'post-materialization timing gap) remains open and unfixed by this change. '
       '[rca_analysis], todo 371.'
FROM config_state WHERE config_key = 'alpha.ic.max_cell_rows';

COMMIT;
