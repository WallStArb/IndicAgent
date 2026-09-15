-- Migration 336: disk-backed Float32ChunkAccumulator APR keys (Phase 174, plan 01).
--
-- Todo 371 (`ic_engine` cross-sectional cell OOM at universe scale): the
-- `alpha.ic.max_cell_rows` crash-loud guard is only reachable AFTER a cell is fully
-- materialized in RAM -- the 5m/high_bear equity cell OOM-killed the process on
-- 2026-09-07 before the guard could ever fire. Migrations 259 and 332 both
-- recalibrated the ceiling upward as a symptom workaround; todo 371 explicitly
-- records that as the anti-pattern this phase (D-04) exists to stop repeating.
-- `alpha.ic.max_cell_rows` itself is NOT recalibrated by this migration -- the fix
-- here is structural (a disk-bounded accumulator whose peak memory is bounded by
-- chunk size, not total cell size), not another ceiling bump.
--
-- Registers exactly two new APR keys, both under the `infra.` prefix (there is no
-- `universe.` prefix in `ConfigService.OPS_PREFIXES`):
--
--   - infra.ic_engine.memmap_scratch_dir: directory holding disk-backed
--     Float32ChunkAccumulator memmap scratch files. Default `/var/tmp/ic_engine_scratch`
--     -- deliberately `/var/tmp`, not `/tmp`: `/tmp` may be tmpfs-backed, which would
--     put the "disk" array back in anonymous RAM and defeat this fix entirely. The
--     directory must have headroom for TWO full cells simultaneously -- Plan 05's
--     `X_raw` and Plan 09's `X_nd` coexist within one cell's compute.
--   - infra.ic_engine.disk_backed_min_rows: pre-flight estimated row-count threshold
--     at or above which a cross-sectional cell uses the disk-backed accumulator;
--     smaller cells stay in-RAM (memmap has real per-cell setup/IO cost not worth
--     paying for small cells). Default 2,000,000; 0 means always-disk-backed.
--
-- Both keys are [initial_estimate] -- no measurement run has calibrated either value
-- yet, this migration only makes the mode reachable. Neither is an ML learning target.
--
-- Idempotent: APR uses ON CONFLICT (config_key) DO NOTHING (migration 292's pattern).
-- Safe to re-run.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'infra.ic_engine.memmap_scratch_dir',
    'str',
    '/var/tmp/ic_engine_scratch',
    NULL, NULL,
    '[initial_estimate] Phase 174 (D-04, todo 371): directory holding disk-backed '
    'Float32ChunkAccumulator memmap scratch files for cross-sectional cell compute at '
    'universe scale. Must live on a filesystem with headroom for TWO full cells '
    'simultaneously (Plan 05''s X_raw and Plan 09''s X_nd coexist within one cell''s '
    'compute). Deliberately /var/tmp, not /tmp -- /tmp may be tmpfs-backed, which would '
    'put the "disk" array back in RAM and defeat this fix entirely. Not an ML learning '
    'target.'
),
(
    'infra.ic_engine.disk_backed_min_rows',
    'int',
    '2000000',
    0, NULL,
    '[initial_estimate] Phase 174 (D-04): pre-flight estimated row-count threshold at '
    'or above which a cross-sectional cell uses the disk-backed accumulator; smaller '
    'cells stay in-RAM because memmap carries real per-cell setup/IO cost not worth '
    'paying for small cells. 0 means always-disk-backed. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('infra.ic_engine.memmap_scratch_dir', '/var/tmp/ic_engine_scratch', 1),
('infra.ic_engine.disk_backed_min_rows', '2000000', 1)
ON CONFLICT (config_key) DO NOTHING;

COMMIT;
