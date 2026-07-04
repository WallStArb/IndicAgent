# DB Institutional Audit — Design Spec

**Date:** 2026-03-19
**Status:** Approved for planning
**Milestone:** v2.0 — Phase 39 (expanded)
**Framing:** What would Simons demand?

---

## Goal

Elevate the database layer from "works in production" to institutional-quality quantitative infrastructure. Five audit dimensions: critical performance, schema constraints + data quality, instrumentation, index optimization, and data repair + quality monitoring. Every change passes the Renaissance filter: does it make the data more complete, more measurable, or more predictively valid?

---

## Section 1: Critical Performance

### 1.1 market_data_ohlcv — Bulk Compress Uncompressed Chunks

**Problem:** 15,740 chunks, most uncompressed. TimescaleDB query planner iterates all chunk metadata on every query — 4-5s timeouts on bounded OHLCV reads.

**Fix:** Compress all chunks older than 7 days in a single migration step. Compressed chunks are excluded by the planner in O(1) via metadata.

```sql
SELECT compress_chunk(c)
FROM   show_chunks('market_data_ohlcv', older_than => INTERVAL '7 days') c
WHERE  NOT EXISTS (
  SELECT 1 FROM timescaledb_information.chunks ch
  WHERE  ch.chunk_schema || '.' || ch.chunk_name = c::regclass::text
    AND  ch.is_compressed
);
```

Run as a standalone script (not inside a migration transaction — `compress_chunk` cannot run in a transaction block).

### 1.2 signal_ledger — Compression Delay 7d → 14d

**Problem:** 1d-TF signals have a 6-bar TTL (~6 days). A signal fired late in a chunk window can receive lifecycle UPDATEs after the 7-day compression policy compresses it — forcing decompress → update → recompress on live rows.

**Fix:**

```sql
WITH j AS (
  SELECT job_id, config AS current_config
  FROM   timescaledb_information.jobs
  WHERE  application_name LIKE '%Compression%'
    AND  hypertable_name = 'signal_ledger'
)
SELECT alter_job(job_id, config => current_config || '{"compress_after": "14 days"}')
FROM   j;
```

### 1.3 Generated Column: `effective_ts`

**Problem:** `ORDER BY COALESCE(signal_computed_at, feature_ts) DESC` appears in 3 API queries. Non-sargable — forces a sort pass on every call. Cannot be indexed.

**Fix:** Stored generated column eliminates runtime COALESCE with zero app changes:

```sql
ALTER TABLE signal_ledger
  ADD COLUMN effective_ts TIMESTAMPTZ
  GENERATED ALWAYS AS (COALESCE(signal_computed_at, feature_ts)) STORED;

CREATE INDEX idx_ledger_effective_ts
  ON signal_ledger (symbol, timeframe, effective_ts DESC);
```

All queries referencing `COALESCE(signal_computed_at, feature_ts)` in ORDER BY or WHERE are updated to `effective_ts`.

### 1.4 Generated Column: `pipeline_lag_ms`

**Problem:** `/signals/stats` runs `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (signal_computed_at - timestamp)) * 1000)` over 30 days of raw rows on every dashboard load.

**Fix:** Stored at write time — zero runtime computation:

```sql
ALTER TABLE signal_ledger
  ADD COLUMN pipeline_lag_ms INT
  GENERATED ALWAYS AS (
    (EXTRACT(EPOCH FROM (signal_computed_at - timestamp)) * 1000)::INT
  ) STORED;

CREATE INDEX idx_ledger_pipeline_lag
  ON signal_ledger (pipeline_lag_ms)
  WHERE pipeline_lag_ms IS NOT NULL;
```

Stats query becomes `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY pipeline_lag_ms)` with index support.

---

## Section 2: Schema Constraints & Data Quality

### 2.1 CHECK Constraints — Status, Outcome, Direction

ML model trained on outcome labels. A corrupted label in 1.8M rows biases the classifier silently. These constraints enforce invariants at the storage layer — the last line of defense.

```sql
ALTER TABLE signal_ledger
  ADD CONSTRAINT chk_signal_ledger_status
  CHECK (status IN ('pending','active','regime_suppressed','expired','resolved'));

ALTER TABLE signal_ledger
  ADD CONSTRAINT chk_signal_ledger_outcome
  CHECK (outcome IS NULL OR outcome IN (
    'never_activated','stopped_at_entry','stopped_in_trade',
    'target_1','target_1_2','target_full',
    'ttl_expired_ahead','ttl_expired_behind',
    'condition_expired'
  ));

ALTER TABLE signal_ledger
  ADD CONSTRAINT chk_signal_ledger_direction
  CHECK (direction IN (-1, 0, 1));
```

`outcome IS NULL` guard is required — outcome is NULL until signal exits.

### 2.2 `signal_performance_segmented` Table

**Problem:** `setup_performance` aggregates only by `setup_plugin` — no regime, no timeframe, no time-of-day. A setup that works at 9am in a trending regime is a different instrument from the same setup at 3pm in mean-reversion. Current aggregator treats them identically.

**Fix:** New table, refreshed every 15 min by `weight_updater`:

```sql
CREATE TABLE signal_performance_segmented (
  setup_plugin    TEXT        NOT NULL,
  regime_type     TEXT        NOT NULL CHECK (regime_type IN ('trend','mean_reversion','any')),
  timeframe       TEXT        NOT NULL,
  hour_et         SMALLINT    NOT NULL CHECK (hour_et BETWEEN 0 AND 23),
  win_rate        NUMERIC(6,4),
  avg_pnl_r       NUMERIC(8,4),
  sharpe          NUMERIC(8,4),
  p_value         NUMERIC(8,6),
  is_significant  BOOLEAN     NOT NULL DEFAULT false,
  sample_size     INT         NOT NULL DEFAULT 0,
  last_refreshed  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (setup_plugin, regime_type, timeframe, hour_et)
);
```

Aggregator reads `perf_multiplier` from `(setup_plugin, regime_type_at_fire, tf, hour_et)` — tighter segmentation than current `setup_plugin`-only lookup.

**Gate:** Only rows with `sample_size >= 30` and `p_value < 0.05` set `is_significant = true`. Aggregator uses `is_significant = true` rows only; falls back to `setup_performance` for unseen segments.

### 2.3 `feature_completeness` Column

**Problem:** A signal fired with empty `i5` and `i6` JSONB blobs has missing pattern and SMC context. Training the ML model on partial-feature rows dilutes signal quality.

**Fix:** Computed at signal fire by `signal_generator_service`, stored at INSERT:

```sql
ALTER TABLE signal_ledger
  ADD COLUMN feature_completeness SMALLINT
  CHECK (feature_completeness BETWEEN 0 AND 100);
```

Computation: `sum(1 for tier in [i1,i3,i4,i5,smc,i6] if tier is non-empty) / 6 * 100`.

ML training gate: `WHERE feature_completeness >= 80 AND is_shadow = false`.

### 2.4 Batch Lifecycle UPDATEs

**Problem:** `signal_lifecycle_service` fires N individual `UPDATE signal_ledger SET trailing_stop_price=... WHERE signal_id=$1` calls per bar — up to 40 active signals × 4 TFs = 160 round-trips per bar cycle.

**Fix:** Batch all chandelier updates for a given bar into one transaction using asyncpg `execute_batch()`:

```python
# In signal_lifecycle_service.py
updates = [
    (
        signal_id,
        json.dumps(trailing_stop_price),
        rate,
        staleness_score,
        staleness_trigger_reason,
        vol_source
    )
    for signal_id, ... in active_signals_this_bar
]

await db_manager.execute_batch(
    _UPDATE_CHANDELIER_SQL,
    updates
)
```

SQL template (idempotent, executed once per batch):
```sql
UPDATE signal_ledger sl
SET    trailing_stop_price           = v.trailing_stop_price::jsonb,
       trailing_stop_tightening_rate = v.rate,
       staleness_score               = v.staleness_score,
       staleness_trigger_reason      = v.staleness_trigger_reason,
       chandelier_vol_source         = COALESCE(sl.chandelier_vol_source, v.vol_source)
FROM   (VALUES
  ($1::uuid, $2, $3::numeric, $4, $5, $6)
) AS v(signal_id, trailing_stop_price, rate, staleness_score, staleness_trigger_reason, vol_source)
WHERE  sl.signal_id = v.signal_id;
```

asyncpg `execute_batch()` calls `executemany()` behind the scenes, which runs the same query N times but within a single transaction. The key optimization is batching multiple updates into one transaction instead of N separate transactions.

---

## Section 3: Instrumentation

### 3.1 `updated_at` Trigger on `signal_ledger`

Every mutable row needs an audit timestamp. Without it, stuck signals (pending for hours) are invisible. Enables: `WHERE status = 'pending' AND updated_at < now() - interval '2 hours'` — operational health query.

```sql
CREATE OR REPLACE FUNCTION fn_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END; $$;

CREATE TRIGGER trg_signal_ledger_updated_at
  BEFORE UPDATE ON signal_ledger
  FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
```

Note: `updated_at` column already exists on `signal_ledger` (nullable). This trigger adds automatic update behavior. A separate migration with data validation may convert the column to `NOT NULL` if desired, but that requires a full table scan and is not required for the trigger to function.

### 3.2 `write_lag_ms` on `intelligence_features`

**As a training feature, not just a debug metric.** The write-path lag `(bar_received_at - computed_at)` is a variable to correlate against signal calibration quality: do signals written under high lag degrade in calibration accuracy? If yes, `write_lag_ms` becomes a ML feature that gates signal quality.

```sql
ALTER TABLE intelligence_features
  ADD COLUMN write_lag_ms INT;
```

Set by `feature_writer_service._process_intelligence_event()`:
```python
write_lag_ms = int((datetime.now(UTC) - computed_at).total_seconds() * 1000)
```

### 3.3 Continuous Aggregate: `signal_stats_hourly`

Replaces the `/signals/stats` full 30-day scan. Adds Information Coefficient — the primary Renaissance signal quality metric.

```sql
-- Verify timescaledb_toolkit is installed (required for percentile_agg)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb_toolkit') THEN
    RAISE EXCEPTION 'timescaledb_toolkit extension required. Install with: CREATE EXTENSION timescaledb_toolkit;';
  END IF;
END $$;

CREATE MATERIALIZED VIEW signal_stats_hourly
WITH (timescaledb.continuous) AS
SELECT
  time_bucket('1 hour', timestamp)        AS bucket,  -- Note: partitioning column, not effective_ts
  symbol,
  timeframe,
  regime_type_at_fire,
  COUNT(*)                               AS n_total,
  COUNT(*) FILTER (WHERE was_selected)   AS n_selected,
  COUNT(*) FILTER (WHERE was_selected
    AND calibrated_confidence >= 0.40
    AND abs(cis_score) > 0.35)           AS n_hero,
  COUNT(*) FILTER (
    WHERE status = 'regime_suppressed')  AS n_regime_suppressed,
  ROUND(AVG(calibrated_confidence)
    FILTER (WHERE was_selected)::numeric, 4)   AS avg_confidence,
  ROUND(AVG(pnl_r)
    FILTER (WHERE pnl_r IS NOT NULL)::numeric, 4) AS avg_pnl_r,
  -- Information Coefficient: correlation between predicted confidence and binary win
  CORR(
    calibrated_confidence,
    CASE WHEN outcome IN ('target_1','target_1_2','target_full') THEN 1.0
         WHEN outcome IS NOT NULL THEN 0.0
         ELSE NULL END
  )                                      AS information_coefficient,
  percentile_agg(pipeline_lag_ms)        AS lag_pctile_agg  -- query: approx_percentile(0.5, lag_pctile_agg)
FROM signal_ledger
WHERE timestamp IS NOT NULL
GROUP BY 1, 2, 3, 4
WITH NO DATA;

-- Real-time union: current bucket served live, not from stale materialized data
ALTER MATERIALIZED VIEW signal_stats_hourly
  SET (timescaledb.materialized_only = false);

SELECT add_continuous_aggregate_policy('signal_stats_hourly',
  start_offset      => INTERVAL '31 days',
  end_offset        => INTERVAL '1 hour',
  schedule_interval => INTERVAL '1 hour');
```

**API change:** `/signals/stats` query becomes:
```sql
SELECT
  SUM(n_hero), SUM(n_selected), SUM(n_total), SUM(n_regime_suppressed),
  AVG(avg_confidence), AVG(avg_pnl_r),
  AVG(information_coefficient) FILTER (WHERE information_coefficient IS NOT NULL),
  approx_percentile(0.5, rollup(lag_pctile_agg)) AS lag_p50_ms
FROM signal_stats_hourly
WHERE bucket >= now() - interval '30 days';
```
O(720 rows) instead of O(30-day raw scan).

---

## Section 4: Index Optimization

### 4.1 Index for `/signals/recent`

```sql
CREATE INDEX idx_ledger_recent
  ON signal_ledger (symbol, timeframe, effective_ts DESC)
  WHERE is_shadow = false;
```

No `INCLUDE` — `/signals/recent` selects 30+ columns; a covering index for a `LIMIT 20` query adds write overhead without meaningful heap-fetch savings. The value is in the filter + sort efficiency.

### 4.2 Drop `idx_signal_ledger_shadow`

```sql
DROP INDEX IF EXISTS idx_signal_ledger_shadow;
```

Boolean single-column index. Never selectivity-useful alone. `idx_ledger_recent` bakes `is_shadow = false` into its predicate. Net-negative on write amplification.

### 4.3 `llm_calls` — Per-Symbol Model Attribution

```sql
CREATE INDEX idx_llm_calls_symbol_model
  ON llm_calls (symbol, model, call_type)
  WHERE symbol IS NOT NULL;
```

Enables: "which model wins on ES specifically?" — core Renaissance segmentation question as adaptive routing matures. Partial on `IS NOT NULL` — symbol-agnostic group synthesis calls excluded.

### 4.4 `signal_performance_segmented` — Significant-Only Index

```sql
CREATE INDEX idx_perf_seg_significant
  ON signal_performance_segmented (setup_plugin, regime_type, timeframe, hour_et)
  WHERE sample_size >= 30 AND is_significant = true;
```

Aggregator only reads statistically valid rows. Index is tiny — covers only the rows that actually influence `perf_multiplier`.

### 4.5 Post-Migration Verification

After every migration run, verify expected indexes are used via `EXPLAIN` on representative queries:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM signal_ledger
WHERE status IN ('pending', 'active', 'regime_suppressed')
  AND symbol = 'ES'
  AND timestamp >= now() - interval '1 day'
ORDER BY timestamp DESC
LIMIT 50;

EXPLAIN (ANALYZE, BUFFERS)
SELECT sl.signal_id, sl.setup_plugin, sl.calibrated_confidence, sl.cis_score, sl.status, sl.outcome
FROM signal_ledger sl
WHERE sl.symbol = 'ES' AND sl.timeframe = '5m' AND sl.is_shadow = false
ORDER BY sl.effective_ts DESC
LIMIT 20;
```

Expected: `Index Scan` using `idx_ledger_open_signals` for the first query, `Index Scan` using `idx_ledger_recent` for the second. `idx_scan` from `pg_stat_user_indexes` is unreliable for hypertable parent indexes (chunk-level indexes are tracked separately).

---

## Section 5: CIS Null Repair + Data Quality Infrastructure

### 5.1 `repair_audit_log` Table

Every repair batch is logged. Enables resumability and distribution sanity checks.

```sql
CREATE TABLE repair_audit_log (
  id              BIGSERIAL PRIMARY KEY,
  repair_name     TEXT        NOT NULL,
  batch_start     TIMESTAMPTZ NOT NULL,
  batch_end       TIMESTAMPTZ NOT NULL,
  rows_examined   INT         NOT NULL,
  rows_repaired   INT         NOT NULL,
  rows_skipped    INT         NOT NULL,
  avg_value       NUMERIC(10,6),         -- distribution sanity: avg of repaired metric
  stddev_value    NUMERIC(10,6),
  started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at    TIMESTAMPTZ,
  status          TEXT        NOT NULL DEFAULT 'running'
    CHECK (status IN ('running','completed','failed','skipped'))
);
```

### 5.2 Temporal-Cursor Batch Repair

Use 7-day time windows as cursors — temporal locality means the `intelligence_features` JOIN partner is in the same buffer cache window.

```python
# repair_cis_nulls.py — corrected approach
BATCH_WINDOW = timedelta(days=7)
DISTRIBUTION_SIGMA_GATE = 2.0  # stop if repaired avg > 2σ from existing distribution

cursor = min_timestamp  # start from oldest signal with NULL cis_score
while cursor < now():
    batch_end = cursor + BATCH_WINDOW

    # Verify JOIN coverage before repairing
    coverage = db.fetchrow("""
        SELECT COUNT(*) AS total,
               COUNT(inf.ts) AS matched
        FROM   signal_ledger sl
        LEFT JOIN intelligence_features inf
          ON  sl.symbol = inf.symbol
          AND sl.feature_ts = inf.ts
          AND sl.feature_tf = inf.tf
        WHERE  sl.cis_score IS NULL
          AND  sl.timestamp >= $1 AND sl.timestamp < $2
    """, cursor, batch_end)

    if coverage['total'] == 0:
        cursor += BATCH_WINDOW
        continue
    if coverage['matched'] / coverage['total'] < 0.80:
        log_audit(batch_start=cursor, batch_end=batch_end,
                  status='skipped', rows_examined=coverage['total'])
        cursor += BATCH_WINDOW
        continue

    # Repair batch
    result = db.execute("""
        UPDATE signal_ledger sl
        SET    cis_score = <recomputed from inf.i1 features>
        FROM   intelligence_features inf
        WHERE  sl.symbol = inf.symbol AND sl.feature_ts = inf.ts AND sl.feature_tf = inf.tf
          AND  sl.cis_score IS NULL
          AND  sl.timestamp >= $1 AND sl.timestamp < $2
          AND  inf.i1 IS NOT NULL
        RETURNING sl.cis_score
    """, cursor, batch_end)

    # Distribution sanity gate
    repaired_avg = mean(r['cis_score'] for r in result)
    if abs(repaired_avg - known_distribution_mean) > DISTRIBUTION_SIGMA_GATE * known_distribution_std:
        raise ValueError(f"Repaired CIS distribution anomaly: {repaired_avg:.4f} vs expected {known_distribution_mean:.4f}")

    log_audit(batch_start=cursor, batch_end=batch_end,
              rows_repaired=len(result), avg_value=repaired_avg, status='completed')
    cursor += BATCH_WINDOW
```

### 5.3 `data_quality_log` Table + Hourly Monitor

```sql
CREATE TABLE data_quality_log (
  checked_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  metric      TEXT        NOT NULL,
  value       NUMERIC(10,4) NOT NULL,
  threshold   NUMERIC(10,4) NOT NULL,
  status      TEXT        NOT NULL CHECK (status IN ('ok','warn','fail')),
  PRIMARY KEY (checked_at, metric)
);

-- Insert pattern with retry-safe upsert
INSERT INTO data_quality_log (checked_at, metric, value, threshold, status)
VALUES (now(), $1, $2, $3, $4)
ON CONFLICT (checked_at, metric)
DO UPDATE SET value = EXCLUDED.value, status = EXCLUDED.status;
```

Metrics checked hourly by a new `data_quality_monitor` job (lightweight, runs in `weight_updater` timer loop):

| Metric | Threshold | Action on fail |
|--------|-----------|----------------|
| `signal_feature_join_coverage_24h` | >= 0.95 | Alert: pipeline gap |
| `cis_null_rate_24h` | <= 0.05 | Alert: CIS computation failing |
| `outcome_null_rate_7d_plus` | <= 0.02 | Alert: lifecycle service stuck |
| `intelligence_features_lag_p95_ms` | <= 500 | Alert: feature_writer lagging |
| `information_coefficient_7d` | >= 0.02 | Warn: model losing edge |

The IC threshold (`>= 0.02`) is the key Renaissance gate — if the model's predictive power drops below 0.02, it triggers a review of calibration and regime detection, not just an ops alert.

---

## Implementation Sequence

Ordered by dependency and risk:

1. **Migration 040** — generated columns (`effective_ts`, `pipeline_lag_ms`), `updated_at` trigger, `feature_completeness` column, `write_lag_ms` column
2. **Migration 041** — CHECK constraints (status, outcome, direction). Validate no existing rows violate constraints before applying.
3. **Migration 042** — `signal_performance_segmented` table + indexes
4. **Migration 043** — `repair_audit_log`, `data_quality_log` tables
5. **Migration 044** — indexes: `idx_ledger_recent`, drop `idx_ledger_shadow`, `idx_llm_calls_symbol_model`, `idx_perf_seg_significant`
6. **Migration 045** — continuous aggregate `signal_stats_hourly` (requires toolkit check first)
7. **Script** — bulk compress `market_data_ohlcv` (outside migration, no transaction)
8. **Script** — batch CIS null repair (temporal cursor, resumable)
9. **App changes** — `signal_lifecycle_service` batch UPDATE, `feature_writer_service` `write_lag_ms`, `signal_generator_service` `feature_completeness`, `weight_updater` populate `signal_performance_segmented`, `aggregator.py` segmented lookup, `/signals/stats` API query update, `data_quality_monitor` job
10. **Post-migration**: Seed `signal_stats_hourly` continuous aggregate — `CALL refresh_continuous_aggregate('signal_stats_hourly', window_start => now() - interval '31 days', window_end => now());`

## App Code Changes Required

| File | Change |
|------|--------|
| `services/signal_lifecycle_service.py` | Batch chandelier UPDATEs via `execute_batch()` |
| `services/feature_writer_service.py` | Set `write_lag_ms` at write time |
| `services/signal_generator_service.py` | Compute + insert `feature_completeness` |
| `src/intelligence/weight_updater.py` | Populate `signal_performance_segmented` every 15 min |
| `src/intelligence/trading/aggregator.py` | Read `perf_multiplier` from `(setup_plugin, regime_type, tf, hour_et)` tuples |
| `services/signal_generator_service.py` | Pass `regime_type_at_fire` and `hour_et` to `aggregate()` calls |
| `src/api/routes/signals.py` | `/signals/stats` reads from `signal_stats_hourly`; ORDER BY `effective_ts` |
| New: `src/core/data_quality_monitor.py` | Hourly metrics → `data_quality_log` |

## Success Criteria

- `/signals/stats` query time < 50ms (from ~4s)
- `market_data_ohlcv` bounded queries < 200ms (from 4-5s)
- signal_ledger lifecycle UPDATE batch: 1 round-trip per bar (from N)
- Zero NULL `cis_score` on signals with available `intelligence_features` JOIN
- `information_coefficient` visible in dashboard stats strip
- `data_quality_log` populated hourly with all 5 metrics green

---

*Design approved in brainstorming session 2026-03-19. Ready for `/gsd:plan-phase` → Phase 39.*
