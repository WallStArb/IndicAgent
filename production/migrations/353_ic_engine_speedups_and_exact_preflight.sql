-- Migration 353: ic_engine speedup bundle (todo 385) + exact pre-flight count cap restore (todo 386)
--
-- Lands with branch perf/ic-engine-speedups, immediately before Phase 176-08's corpus IC run,
-- which recomputes every cell anyway (plans 176-04/176-06 already moved code_content_key).
--
-- 1. alpha.ic.bootstrap_numba_kernel = true (new, COMPUTATIONAL fingerprint field). Routes the
--    circular block bootstrap through the counting-rank numba kernel
--    (src/intelligence/statistics/ic_bootstrap_jit.py). SPY 1h end to end at 2 threads: 338.7s
--    (scipy) -> 16.7s; CI bounds within 2.3e-8 of the scipy path over 5706 rows, zero gate
--    flips. Computational, not operational: scipy >= 1.15 keeps float32 ranks, so the scipy path
--    accumulates in float32 while the kernel accumulates in float64.
--
-- 2. infra.ic_engine.cs_fetch_connections = 12 (new, OPERATIONAL). The cross-sectional stage was
--    bound by single-threaded chunk-query decompression (equity 1h high_neutral: 87s of 137s
--    waiting on Postgres). Chunks now run on concurrent connections and are consumed in order.
--
-- 3. Operational layout changes (none are fingerprint fields; changing them never invalidates a
--    cell). Measured on the kernel: per-core throughput is best at low thread counts (SPY 1h: 1
--    thread 26.9s, 2 threads 16.7s), and memory (~3.8 GB peak per 5m worker, 29 GB box) caps the
--    worker count, so the 8 workers production already ran safely get 3 threads each (24
--    threads on 24 cores). The cross-sectional stage runs alone after the per-symbol pass, so it
--    takes the schema maximum of 16 bootstrap threads, and smaller fetch chunks bound the rows
--    in flight across 12 connections (equity 1h high_neutral: 130.3s -> 52.2s, bit-identical).
--      infra.ic_engine.per_symbol_bootstrap_threads.{5m,15m,1h,1d}: 2 -> 3
--      alpha.ic.cross_sectional_bootstrap_threads.{5m,15m,1h,1d}: 6/8 -> 16
--      infra.ic_engine.cs_chunk_ts: 2000 -> 250
--
-- 4. alpha.ic.max_cell_rows: 100,000,000 -> 15,000,000. Migration 347 raised it only because the
--    pre-flight used a full-density estimate that overstated real cells 3-13x. Todo 386 replaces
--    it with an exact count (largest real cell measured 2026-09-23: equity/5m/mid_neutral,
--    10,231,947 rows), so the original ceiling applies again.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'alpha.ic.bootstrap_numba_kernel',
    'bool',
    'false',
    NULL, NULL,
    '[rca_analysis] Todo 385 lever 2: run the ic_engine circular block bootstrap through the '
    'counting-rank numba kernel instead of the scipy resample loop (~20x on SPY 1h at equal '
    'threads). COMPUTATIONAL: part of the cell fingerprint, so changing it invalidates every '
    'cell (the kernel accumulates in float64, the scipy path in float32). Not an ML learning '
    'target.'
),
(
    'infra.ic_engine.cs_fetch_connections',
    'int',
    '1',
    1, 32,
    '[rca_analysis] Todo 385: concurrent database connections running a cross-sectional '
    'cell''s chunk queries. Results are consumed in chunk order, so the fetched arrays are '
    'identical for any value (operational). Rows in flight scale with this times '
    'infra.ic_engine.cs_chunk_ts. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('alpha.ic.bootstrap_numba_kernel', 'true', 1),
('infra.ic_engine.cs_fetch_connections', '12', 1)
ON CONFLICT (config_key) DO NOTHING;

UPDATE config_state SET config_value = '3', version = version + 1, updated_at = NOW()
WHERE config_key IN (
    'infra.ic_engine.per_symbol_bootstrap_threads.5m',
    'infra.ic_engine.per_symbol_bootstrap_threads.15m',
    'infra.ic_engine.per_symbol_bootstrap_threads.1h',
    'infra.ic_engine.per_symbol_bootstrap_threads.1d'
);

UPDATE config_state SET config_value = '16', version = version + 1, updated_at = NOW()
WHERE config_key IN (
    'alpha.ic.cross_sectional_bootstrap_threads.5m',
    'alpha.ic.cross_sectional_bootstrap_threads.15m',
    'alpha.ic.cross_sectional_bootstrap_threads.1h',
    'alpha.ic.cross_sectional_bootstrap_threads.1d'
);

UPDATE config_state SET config_value = '250', version = version + 1, updated_at = NOW()
WHERE config_key = 'infra.ic_engine.cs_chunk_ts';

UPDATE config_state SET config_value = '15000000', version = version + 1, updated_at = NOW()
WHERE config_key = 'alpha.ic.max_cell_rows';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, version, config_value, 'migration_353',
       CASE
         WHEN config_key = 'alpha.ic.bootstrap_numba_kernel' THEN
           'Seeded true: counting-rank numba bootstrap kernel, ~20x on SPY 1h, CI bounds within '
           '2.3e-8 of scipy with zero gate flips. Computational field. [rca_analysis], todo 385.'
         WHEN config_key = 'infra.ic_engine.cs_fetch_connections' THEN
           'Seeded 12: concurrent ordered cross-sectional chunk fetch, identical arrays. '
           '[rca_analysis], todo 385.'
         WHEN config_key LIKE 'infra.ic_engine.per_symbol_bootstrap_threads.%' THEN
           '2 -> 3: 8 workers x 3 kernel threads fills 24 cores; per-core throughput is best '
           'at low thread counts and memory caps the worker count. Operational. todo 385.'
         WHEN config_key LIKE 'alpha.ic.cross_sectional_bootstrap_threads.%' THEN
           '-> 16 (schema max): the cross-sectional stage runs alone after the per-symbol pass. '
           'Operational. todo 385.'
         WHEN config_key = 'infra.ic_engine.cs_chunk_ts' THEN
           '2000 -> 250: bounds rows in flight across 12 concurrent fetch connections. '
           'Operational. todo 385.'
         WHEN config_key = 'alpha.ic.max_cell_rows' THEN
           '100,000,000 -> 15,000,000: restores the ceiling migration 347 raised; the pre-flight '
           'now uses an exact row count (largest real cell 10,231,947). [rca_analysis], todo 386.'
       END
FROM config_state
WHERE config_key IN (
    'alpha.ic.bootstrap_numba_kernel',
    'infra.ic_engine.cs_fetch_connections',
    'infra.ic_engine.per_symbol_bootstrap_threads.5m',
    'infra.ic_engine.per_symbol_bootstrap_threads.15m',
    'infra.ic_engine.per_symbol_bootstrap_threads.1h',
    'infra.ic_engine.per_symbol_bootstrap_threads.1d',
    'alpha.ic.cross_sectional_bootstrap_threads.5m',
    'alpha.ic.cross_sectional_bootstrap_threads.15m',
    'alpha.ic.cross_sectional_bootstrap_threads.1h',
    'alpha.ic.cross_sectional_bootstrap_threads.1d',
    'infra.ic_engine.cs_chunk_ts',
    'alpha.ic.max_cell_rows'
);

COMMIT;
