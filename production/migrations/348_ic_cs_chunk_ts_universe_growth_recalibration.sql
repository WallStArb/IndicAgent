-- Migration 348: infra.ic_engine.cs_chunk_ts recalibrated for universe growth
--
-- The description on this key says it was sized for "5000 x 58 symbols = 290K rows per query"
-- to avoid a PostgreSQL backend OOM on the cross-sectional 3-way JOIN. The equity regime group
-- is now 182 symbols (not 58), so the same 5000-timestamp chunk pulls about 910K rows per query,
-- roughly 3x the design target. Observed 2026-09-21 during the 2026-09-17 corpus run's rerun: the
-- 5m low_neutral cell (11.2M real rows) held the ic_engine main process's anonymous memory at
-- 20-26 GB during its data-load phase (chunked query -> Python objects -> float32 conversion),
-- pushing available system RAM below 1 GB and swap activity as high as ~600 MB/s several times.
-- No OOM kill occurred (96 GB swapfile absorbed it), but the same shape of failure killed a prior
-- run at this exact stage (todo 371, 2026-09-07, 5m/high_bear, kernel OOM-killer).
--
-- New value: 2000, giving about 364,000 rows per query at 182 symbols -- close to the original
-- 290K design target. Purely a throughput/memory-shape knob (infra.ic_engine.cs_chunk_ts is in
-- ic_engine.py's _COMPUTATIONAL_CONFIG_FIELDS exclusion list, "pure throughput knob"), so this
-- does not invalidate any cell's fingerprint; only a process restart picks it up (config is read
-- once at startup, not hot-reloaded). More, smaller queries per cell; expected to cost a little
-- wall time in exchange for a materially lower peak memory footprint on the largest remaining
-- cells (5m mid_neutral, 12.5M real rows, not yet computed as of this migration).

BEGIN;

UPDATE config_state
SET config_value = '2000', version = version + 1, updated_at = NOW()
WHERE config_key = 'infra.ic_engine.cs_chunk_ts';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'infra.ic_engine.cs_chunk_ts', version, config_value, 'migration_348',
       'Lowered from 5000 to 2000 timestamps per chunk. The original sizing (5000 x 58 symbols '
       '= 290K rows/query) predates the equity group growing to 182 symbols; at 182 symbols the '
       'same chunk size pulls ~910K rows/query, driving the ic_engine main process to 20-26 GB '
       'anonymous memory during a large cell''s load phase (observed 2026-09-21, 5m low_neutral, '
       '11.2M rows). 2000 restores ~364K rows/query, near the original target. Pure throughput '
       'knob, excluded from the cell fingerprint. [rca_analysis], todo 371.'
FROM config_state WHERE config_key = 'infra.ic_engine.cs_chunk_ts';

COMMIT;
