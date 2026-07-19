-- Migration 208: APR key for the interaction-primitives pilot's chunked-fetch
-- flush interval (todo 037, Task 3 v3 memory-blowup fix).
--
-- scripts/ops/alpha/ops_interaction_primitives_pilot.py's _fetch_tf_dataset()
-- previously accumulated every row of a tf's feature_vectors partition into
-- unbounded Python-object lists (raw_by_symbol) before a one-shot numpy
-- conversion at the end. For tf='5m' (~25.35M rows x ~25 columns) this drove
-- system MemAvailable to ~1.4GB and swap-out to ~98MB/s within 7 minutes -- killed
-- preemptively before an actual OOM (Task 5's second attempt; the bounded sanity
-- checks in both prior reviews only exercised tf='1d', the smallest partition, so
-- this risk was never actually tested at the scale that broke).
--
-- _fetch_tf_dataset() now flushes raw_by_symbol to per-symbol numpy chunk-arrays
-- every `flush_rows` rows (a running counter across the whole tf), bounding peak
-- Python-list accumulation memory regardless of total tf row count -- same
-- "batch size to bound memory during a large streamed fetch" concept as
-- infra.ensemble_ic_engine.pooled_fetch_itersize (migration 209) and
-- infra.ic_engine.cs_chunk_ts (migration 183) applied to this sibling script.
--
-- Scope of what this bounds: only the TRANSIENT Python-object-list buffer
-- during accumulation. The function's OUTPUT -- the fully concatenated
-- per-symbol numpy dataset for the whole tf partition -- still must reside in
-- RAM in its entirety for _slice_cell() to iterate over (tf='5m' is
-- ~25.35M rows x ~21 float64 columns, ~4.3GB resident). flush_rows does
-- nothing to bound that resident ceiling; it was safe at today's tested
-- scale (2026-07-10 live run: ~9.8GB peak RSS on a 29GB box, completed
-- cleanly) but a future timeframe/symbol/column-count increase would raise
-- it with no APR knob to mitigate.
--
-- Sizing: 500,000 rows x ~25 cols x ~32 bytes/Python-float-object overhead is
-- approx 400MB -- keeps the transient accumulation buffer well under a few
-- hundred MB, regardless of total tf row count. This is a memory-safety
-- parameter, not a correctness one, so the exact value isn't precision-critical.
--
-- [initial_estimate] [infra.interaction_primitives_pilot] -- tunable but not an
-- ML learning target.
BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES (
    'infra.interaction_primitives_pilot.fetch_flush_rows',
    'int',
    '500000',
    1000, 10000000,
    '[initial_estimate] Row count after which _fetch_tf_dataset() in '
    'scripts/ops/alpha/ops_interaction_primitives_pilot.py flushes its per-symbol '
    'raw_by_symbol Python-object buffers to numpy chunk-arrays (Task 3 v3 memory-'
    'blowup fix, todo 037). Bounds only the TRANSIENT Python-list accumulation '
    'buffer during the tf partition scan (tf=5m is ~25.35M rows) -- the fully '
    'concatenated per-symbol dataset this produces still resides in RAM for the '
    'whole tf (~4.3GB for tf=5m), which this key does not bound. Sized so the '
    'transient buffer stays well under a few hundred MB peak (500,000 rows x 25 '
    'cols x ~32 bytes/Python-float-object overhead approx 400MB). Memory-safety '
    'tuning knob, not a correctness gate -- not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.interaction_primitives_pilot.fetch_flush_rows', '500000', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (
    NOW(), 'infra.interaction_primitives_pilot.fetch_flush_rows', 1, '500000',
    'migration_215',
    'Initial estimate: sized to keep peak Python-list memory under a few hundred '
    'MB during the tf=5m (~25.35M row) chunked fetch [initial_estimate]'
);

COMMIT;
