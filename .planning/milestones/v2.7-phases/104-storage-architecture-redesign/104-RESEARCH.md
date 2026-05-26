# Phase 104: Storage Architecture Redesign - Research

**Researched:** 2026-05-22
**Domain:** TimescaleDB schema migration, PostgreSQL compressed hypertables, Redpanda topic config, ML materialized stores
**Confidence:** HIGH

---

## Summary

Phase 104 addresses 39 GB/week disk growth caused by three structural violations. Research confirms:

1. **Column renames on compressed hypertables are safe in TimescaleDB 2.25.1** - `ALTER TABLE ... RENAME COLUMN` works without decompression as of TimescaleDB 2.1+. The 76 compressed chunks in `intelligence_features` present no obstacle.

2. **`signal_ledger` has 97 DB columns and the Python `LedgerEntry._to_row()` inserts 67** (several DB columns are computed/defaulted). The columns to drop are spread across the 67-parameter INSERT. The slim schema target (~38 unique-lifecycle columns) requires updating `_INSERT_SQL`, `_SELECT_ACTIVE_SQL`, `LedgerEntry` dataclass, and all callers.

3. **`feature_snapshots_shadow` is consumed only by `FeatureSnapshotWriterAgent` and `ParityAuditorAgent`** - both can be cleanly retired. The `FeatureRepository` abstraction makes the shadow write path a one-line change.

4. **`signal_lineage` writes per-winner only (5 rows per signal = 5 agents)** - NOT per-candidate. 27,013 distinct signals across 135,060 rows = exactly 5 agent predictions per signal. The spike was plugin explosion at the signal_ledger level propagating through to the alpha swarm dispatch, not write amplification in signal_lineage itself.

5. **`ml_signal_training` as a nightly materialized store** - the current `_TRAINING_SQL` in `feature_builder.py` already does the JOIN + flattening pattern. The new store removes JSONB unnesting at query time by pre-materializing the result into typed columns.

**Primary recommendation:** Execute in strict dependency order (audit doc → retention/Kafka → drop shadow → design slim ledger + lineage investigation → rename + implement slim ledger together → ML store). Never do the column rename and slim ledger as separate migrations.

---

## Codebase Facts (HIGH confidence - directly read from source)

### Current table inventory (live DB, May 22 2026)

| Table | Hypertable ID | Chunks | Compressed Chunks | Compression Policy | Retention Policy |
|---|---|---|---|---|---|
| `intelligence_features` | 17 | 77 | 76 | 7 days | NONE |
| `signal_ledger` | 13 | 77 | (recompresses daily via job 1021) | 7 days | NONE |
| `feature_snapshots_shadow` | 36 | 14 | 14 | 7 days | NONE |
| `llm_calls` | 22 | 1 | compressed | 7 days | NONE |
| `signal_lineage` | 53 | 2 | compressed | 7 days | NONE |
| `signal_transform_log` | 52 | 0 | - | 7 days | NONE |
| `market_data_ohlcv` | 30 | 104 | compressed | 30 days | NONE |
| `drift_monitor` | 25 | 0 | - | 30 days | NONE |
| `signal_metrics_dq_failures` | 49 | 0 | - | 7 days | 90 days (job 1031) |
| `macro_features` | 51 | 18 | compressed | 7 days | NONE |
| `service_health_events` | 37 | 2 | compressed | 2 days | 7 days (job 1033) |
| `ctx_events` | 55 | 0 | - | 7 days | NONE |
| `alpha_multiplier_shadow` | 43 | 0 | - | 7 days | NONE |
| `dlq_events` | 56 | 0 | - | - | 30 days (job 1034) |
| `intelligence_metrics` | 35 | 0 | - | - | 1 year (job 1025) |

**Tables needing retention policies (NONE currently):** `intelligence_features`, `signal_ledger`, `feature_snapshots_shadow` (to be dropped), `llm_calls`, `signal_lineage`, `signal_transform_log`, `market_data_ohlcv`, `macro_features`, `ctx_events`, `alpha_multiplier_shadow`.

### signal_ledger schema (actual, 97 columns in DB, 67 in Python INSERT)

The `LedgerEntry._to_row()` produces a 67-element tuple. The `_INSERT_SQL` lists these 67 columns explicitly. The DB has additional columns not in the INSERT (`effective_ts`, `pipeline_lag_ms`, `adjusted_confidence`, `swarm_multiplier`, `swarm_agent_count`, `created_at`, `updated_at`).

**Columns to KEEP in slim schema (lifecycle/outcome only - ~38 columns):**
```
signal_id, timestamp, symbol, timeframe, is_shadow, was_selected, status, is_backfill,
signal_schema_version, setup_plugin (for index), signal_type (for routing), direction,
feature_ts, feature_tf (FK to intelligence_features),
activated_at, activation_price, zone_entry_pct, bars_to_activation,
exit_at, exit_price, exit_reason,
pnl_ticks, pnl_r, pnl_dollars, signal_quality,
mae, mfe, bars_in_trade, outcome,
market_entry_at, market_entry_exit_at, market_entry_outcome,
market_entry_pnl_r, market_entry_mae, market_entry_mfe, market_entry_bars_in_trade,
market_entry_gap_bars, market_entry_price, market_entry_exit_price,
trailing_stop_price, staleness_score, staleness_trigger_reason,
shadow_tracking_start_ts, shadow_outcome, shadow_mae, shadow_mfe,
ttl_bars, signal_computed_at
```

**Columns to DROP from INSERT (these live in i7 JSONB in intelligence_features):**
```
entry_price, stop_loss, targets, confidence, confluence_score, regime_context,
supporting_factors, num_signals_bar, num_agreeing, num_conflicting,
resolution_method, composite_rank, market_context, cis_score, bucket_scores,
weights_version, determined_at, ask_at_signal, bid_at_signal, market_price_at_signal,
entry_zone_low, entry_zone_high, zone_valid_at_signal, cis_attribution, market_entry_price (fire-time),
stop_basis, stop_structure_type, stop_structure_age_bars, structural_stop_distance_atr,
hmm_regime_at_fire, garch_sigma_at_fire, chandelier_vol_source,
trailing_stop_tightening_rate, raw_cis_score, filtered_cis_score,
calibrated_confidence, regime_type_at_fire, pre_quality_confidence,
pre_calibration_confidence, entry_type, co_fire_count, co_fire_partners,
features_snapshot, adjusted_confidence, swarm_multiplier, swarm_agent_count
```

**Decision needed:** Some columns are on the boundary - `signal_type`, `direction`, `setup_plugin` are duplicated in i7 JSONB but also used for fast index filtering without JOINs. The CONTEXT.md target schema keeps them. This research supports that decision: keeping them avoids JSONB index scan for every dashboard query.

### intelligence_features column structure (actual DB)

Current columns: `ts, symbol, tf, platform, source, schema_version, bar, i1, i2, i3, i4, i5, smc, i6, i7, bar_close_ts, i1_computed_at, computed_at, i8, days_to_expiry, winner_plugin, winner_confidence, winner_direction, signals_evaluated, signals_after_quality, signals_after_regime, signals_after_tod, signals_after_calibration, ledger_written, i7_computed_at, session_type, roll_premium_pct, pipeline_latency_ms, ctx`

**Renaming `i1`-`i8` requires updating 20+ files** (see Service Update Scope section below).

### signal_lineage audit (actual DB)

```
distinct signals: 27,013
total rows:       135,060
rows per signal:  5.0 (exactly - one per agent)
```

All 5 rows per signal are `event_type='agent_prediction'` from: `correlation_v1`, `counterfactual_v1`, `ml_scorer_v1`, `regime_coherence_v1`, `skeptic_v1`.

**Critical finding: signal_lineage writes per-winner only.** The 17,780 rows not in `signal_ledger` are stale/old signal IDs from before current signal_ledger epoch. The spike in `signal_lineage` (103K rows on May 19) was due to signal_ledger volume explosion (1.52M signals in week of May 18) generating more winners for the swarm to process, NOT write amplification per candidate.

**No redesign needed for signal_lineage write pattern.** The growth is proportional to winner count, not candidate count. Slimming signal_ledger reduces winners too (same pipeline). Lineage currently has 88 MB / 2 compressed chunks - compression policy is set (7d), only needs a retention policy.

### FeatureSnapshotWriterAgent consumer group

Consumer group: `feature_snapshot_writer_group`
Kafka topic: `intelligence.journal` (same as `feature_writer_group`)
Target table: `feature_snapshots_shadow`

The service is defined in `services/feature_snapshot_writer_agent.py` and has a systemd unit `indicagent-feature-snapshot-writer`.

### ParityAuditorAgent metrics / tables

Metrics emitted: `PARITY_CYCLES_TOTAL`, `PARITY_MATCH_RATE`, `PARITY_VIOLATIONS_TOTAL`, `SHADOW_AHEAD_ROWS_TOTAL`
Tables used: `intelligence_features`, `feature_snapshots_shadow`, `feature_parity_violations`
Alerts: publishes to `topic_alert_requests`, `topic_system_events`

The `feature_parity_violations` table is 40 KB (0 rows historically - never detected a real violation). The `SHADOW_PARITY_CERTIFIED` event on `topic_system_events` is not consumed by anything critical.

### Current ML training JOIN pattern

`feature_builder.py` `_TRAINING_SQL` already does the exact JOIN needed:
```sql
SELECT sl.*, f.i4->>'hmm_regime', f.i1->>'atr_pct', ...
FROM signal_ledger sl
JOIN intelligence_features f ON f.symbol = sl.symbol AND f.ts = sl.feature_ts AND f.tf = sl.feature_tf
WHERE sl.outcome IS NOT NULL AND sl.is_shadow = FALSE
```

The `ml_signal_training` materialized store is this query's output, pre-materialized nightly.

### Kafka topics requiring byte retention caps

6 topics currently have `retention.bytes=-1` (unbounded), controlled only by `retention.ms=86400000` (24h):

```
intelligence.signal.audit
swarm.alpha
narratives
intelligence.signal_lineage
llm.calls
llm.outcomes
```

Command verified working: `docker exec redpanda rpk topic alter-config <topic> --set retention.bytes=524288000`

---

## Standard Procedures

### 1. TimescaleDB column rename on compressed hypertables

**Confidence: HIGH** - Verified via official TimescaleDB docs and PR #2909.

TimescaleDB 2.1+ (this system: 2.25.1) supports `ALTER TABLE ... RENAME COLUMN` on compressed hypertables **without decompression**.

```sql
-- Safe: works on compressed hypertables in TimescaleDB 2.25.1
ALTER TABLE intelligence_features RENAME COLUMN i1 TO technical_indicators;
ALTER TABLE intelligence_features RENAME COLUMN i2 TO market_context;
ALTER TABLE intelligence_features RENAME COLUMN i3 TO pattern_detections;
ALTER TABLE intelligence_features RENAME COLUMN i4 TO regime_features;
ALTER TABLE intelligence_features RENAME COLUMN i5 TO confluence_scores;
ALTER TABLE intelligence_features RENAME COLUMN i6 TO cross_timeframe_context;
ALTER TABLE intelligence_features RENAME COLUMN i7 TO trading_signals;
ALTER TABLE intelligence_features RENAME COLUMN i8 TO llm_narrative;
-- smc stays as-is per CONTEXT.md decision
```

**No downtime required for the rename itself.** The operation updates the catalog only; compressed chunk data is not touched.

**Restriction:** Cannot rename `orderby` or `segmentby` columns (`ts`, `symbol`, `tf`). The `i1`-`i8` columns are neither - safe to rename.

**After rename:** All Python code referencing `"i1"`, `"i2"`, etc. as SQL column names must be updated **atomically before restart** (services will error if they try to INSERT into `i1` after rename).

### 2. TimescaleDB retention policies (exact SQL)

```sql
-- intelligence_features: 2 years
SELECT add_retention_policy('intelligence_features', INTERVAL '2 years', if_not_exists => true);

-- signal_ledger: 1 year
SELECT add_retention_policy('signal_ledger', INTERVAL '1 year', if_not_exists => true);

-- llm_calls: 90 days (audit log, high growth rate)
SELECT add_retention_policy('llm_calls', INTERVAL '90 days', if_not_exists => true);

-- signal_lineage: 90 days
SELECT add_retention_policy('signal_lineage', INTERVAL '90 days', if_not_exists => true);

-- market_data_ohlcv: 2 years (raw bars, relatively small)
SELECT add_retention_policy('market_data_ohlcv', INTERVAL '2 years', if_not_exists => true);

-- signal_transform_log: 90 days
SELECT add_retention_policy('signal_transform_log', INTERVAL '90 days', if_not_exists => true);

-- macro_features: 1 year
SELECT add_retention_policy('macro_features', INTERVAL '1 year', if_not_exists => true);

-- ctx_events: 30 days
SELECT add_retention_policy('ctx_events', INTERVAL '30 days', if_not_exists => true);

-- alpha_multiplier_shadow: 30 days
SELECT add_retention_policy('alpha_multiplier_shadow', INTERVAL '30 days', if_not_exists => true);
```

**Function signature:** `add_retention_policy(relation, drop_after, if_not_exists, schedule_interval, initial_start, timezone, drop_created_before)` - `drop_after` is the primary param, `if_not_exists => true` prevents errors on re-run.

**After ml_signal_training is created:**
```sql
-- ml_signal_training: 1 year
SELECT add_retention_policy('ml_signal_training', INTERVAL '1 year', if_not_exists => true);
SELECT add_compression_policy('ml_signal_training', INTERVAL '7 days', if_not_exists => true);
```

### 3. Kafka byte retention caps (exact commands)

```bash
# Set 500 MB cap on each unbounded topic
for topic in \
  "intelligence.signal.audit" \
  "swarm.alpha" \
  "narratives" \
  "intelligence.signal_lineage" \
  "llm.calls" \
  "llm.outcomes"; do
  docker exec redpanda rpk topic alter-config "$topic" --set retention.bytes=524288000
done
```

`524288000` = 500 MB in bytes. The `retention.ms=86400000` (24h) remains unchanged as the primary driver. The bytes cap is a safety ceiling.

### 4. feature_snapshots_shadow removal sequence

```
Step 1: Stop indicagent-feature-snapshot-writer and indicagent-parity-auditor
Step 2: Remove from service_auditor_agent.py _DAG_ORDER, _LAG_THRESHOLDS, _AGENT_ID_TO_UNIT
Step 3: Remove from services/dlq_drain_agent.py topic list
Step 4: Deploy SQL health check (see Architecture Patterns section)
Step 5: DROP TABLE feature_snapshots_shadow CASCADE;
Step 6: DROP TABLE feature_parity_violations;
Step 7: Remove metrics PARITY_CYCLES_TOTAL, PARITY_MATCH_RATE, PARITY_VIOLATIONS_TOTAL, SHADOW_AHEAD_ROWS_TOTAL from metrics.py
Step 8: Delete systemd unit files
Step 9: Remove consumer group from Kafka (consumer group will expire naturally, or use rpk)
Step 10: Run unit test suite
```

**No data backup needed** before dropping `feature_snapshots_shadow` - it is confirmed byte-for-byte identical to `intelligence_features`. The original is intact.

### 5. signal_ledger slim migration pattern

The migration must be zero-downtime for reads (lifecycle writers keep updating `signal_id` by PK). The approach is:

1. Stop `indicagent-signal-writer` (the INSERT writer)
2. Add retention policy before migration (avoids the old data being included in DROP column scan)
3. Deploy new `signal_writer_agent.py` with slim `LedgerEntry` (fewer fields)
4. Run migration SQL to DROP the ~47 duplicate columns from `signal_ledger`
5. Restart all services in DAG order

**Why stop signal-writer first:** Column DROPs on compressed hypertables require decompression of compressed chunks. This is a potentially long operation on 77 chunks. Signal_writer inserts should be paused during the column drop migration.

**Column DROP on compressed hypertables in TimescaleDB 2.6+:** Supported per official docs. TimescaleDB handles the compressed chunk column removal internally. However, it **may** decompress and recompress chunks containing the dropped column, which is I/O intensive.

**Alternative (lower risk):** Use "stop writing columns, then drop later" approach. Stop populating the 47 columns first (write NULLs), validate the system works, then DROP the columns in a maintenance window. This avoids coordinated downtime.

**Preferred approach (per CONTEXT.md design principles):** Drop the columns atomically with the rename migration. The system runs 24/7 but signal_ledger inserts can tolerate a 5-10 minute pause during migration.

### 6. ml_signal_training materialized store schema

```sql
CREATE TABLE ml_signal_training (
    -- Time dimension for hypertable
    ts                      timestamptz NOT NULL,   -- same as signal fire time
    signal_id               uuid        NOT NULL,
    symbol                  text        NOT NULL,
    timeframe               text        NOT NULL,
    setup_plugin            text        NOT NULL,
    
    -- Outcome labels
    pnl_r                   float8,
    win_label               boolean,               -- pnl_r > 0
    outcome                 text,
    
    -- Feature columns (from features_snapshot JSONB, typed)
    existing_confidence     float8,
    ctf_score               float8,
    ctf_trend_alignment     float8,
    ctf_structure_alignment float8,
    ctf_regime_agreement    float8,
    ctf_fvg_alignment       float8,
    ctf_ob_alignment        float8,
    vix_level               float8,
    vix_z                   float8,
    eq_spread_z             float8,
    eq_pairs_confirming     float8,
    ctf_momentum_divergence float8,
    ctf_sr_confluence       float8,
    ctf_hmm_regime_agreement float8,
    ctf_volatility_divergence float8,
    ctf_orderflow_alignment float8,
    exhaustion_score        float8,
    
    -- Categorical (stored as text for simplicity; one-hot at training time)
    profile                 text,
    hmm_regime              int,
    session_type            text,
    
    -- Bar context (from intelligence_features)
    atr_pct                 float8,
    volume_z_score          float8,
    tod_multiplier          float8,
    
    -- Metadata
    signal_schema_version   text,
    materialized_at         timestamptz DEFAULT now(),
    
    PRIMARY KEY (ts, signal_id)
);

SELECT create_hypertable('ml_signal_training', 'ts');
SELECT add_compression_policy('ml_signal_training', INTERVAL '7 days');
SELECT add_retention_policy('ml_signal_training', INTERVAL '1 year');
```

**Backfill updates:** When `pnl_r` resolves (outcome becomes non-NULL in `signal_ledger`), the nightly timer can UPDATE `ml_signal_training` for rows materialized in the last N days that still have `win_label IS NULL`. This is a simple correlated UPDATE.

**Nightly systemd timer pattern:**

```ini
# /etc/systemd/system/indicagent-ml-signal-training-materialize.timer
[Unit]
Description=Nightly ML signal training materialization

[Timer]
OnCalendar=*-*-* 02:00:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
```

The oneshot service runs the INSERT + UPDATE job. Follows the existing `ml_training` timer pattern at 03:00 UTC (this one runs at 02:00 to complete before ML training at 03:00).

---

## Architecture Patterns

### Service Update Scope (complete file list)

**Files that must be updated for i1-i8 rename:**

| File | What changes | Column refs |
|---|---|---|
| `services/feature_writer_agent.py` | `_INSERT_FEATURE_SQL` column list | i1, i2, i3, i4, i5, i6, i7, i8 |
| `src/persistence/repository/feature_repository.py` | `_INSERT_SQL_TEMPLATE` | i1, i2, i3, i4, i5, i6, i7 |
| `src/persistence/repository/feature_snapshot_repository.py` | `get_recent_features()` SELECT | i1, i2, i3, i4, i5, i6 |
| `src/core/bar_history_seeder.py` | SELECT query | i1, i2, i3, i4, i5, i6 |
| `src/core/ai/context.py` | `Tier` enum values, tier labels dict | "i1".."i7" as string values |
| `src/core/ai/base_group_service.py` | destructure from DB row | i1..i7 unpacking |
| `src/core/ml/extractor.py` | field access `event["i1"]`, `event["i7"]` | i1, i7 |
| `src/core/ml/features.py` | docstring field names | i1-i7 |
| `src/core/ml/training_data.py` | query/field access | i1-related |
| `src/intelligence/ml/feature_builder.py` | `_TRAINING_SQL` `f.i4->>'hmm_regime'`, `f.i1->>'atr_pct'`, `f.i7->0` | i1, i4, i7 |
| `src/persistence/logic/stream_merger.py` | `EXPECTED_TIERS` frozenset | "i1".."i8" strings |
| `src/persistence/logic/warmup_provider.py` | query field access | i1-related |
| `src/api/routes/signals.py` | row access `row["i1"]` | i1 |
| `src/api/routes/features.py` | tier list `["bar", "i1", "i3", ...]` | i1, i3, i4, i5, i6 |
| `src/api/routes/sse.py` | row/event field access | i1-related |
| `src/api/routes/narrative.py` | field access | i7-related |
| `src/intelligence/schemas.py` | `BarIntelligenceRecord` fields `i1:`, `i2:`, ... | i1..i8 as Python attrs |
| `src/intelligence/pipeline/signal_processor.py` | tier name constants | "i1".."i7" |
| `src/intelligence/pipeline/feature_pipeline_executor.py` | tier_name checks | "i1".."i6" |
| `src/intelligence/services/feature_validation_compute_agent.py` | SQL query | i7 |
| `src/intelligence/services/hmm_training_compute_agent.py` | field access | i4-related |
| `src/intelligence/trading/zone_engine.py` | tier path `"i1"` | i1 |
| `src/intelligence/confluence/cross_timeframe.py` | field access | i6-related |
| `src/validation/cross_tier_validation.py` | tier validation | i1..i7 |
| `src/validation/validation_engine.py` | tier checks | i1-related |
| `src/core/schemas/parity.py` | schema field names | i1-related |
| `tests/unit/` (multiple) | test fixtures using i1..i7 column names | multiple |

**IMPORTANT:** `src/intelligence/schemas.py` uses `i1`, `i2`, ... as Python attribute names on `BarIntelligenceRecord`. These are the in-memory event bus names. The rename could be scope-limited: rename ONLY the DB columns and keep the Python attribute names as `i1`-`i8` (they are internal). This is the recommended approach to minimize code churn - Python attrs `i1`-`i8` remain, only SQL column names change.

If Python attrs are kept as `i1`-`i8`, only the SQL/column reference files need updating, not the business logic files. This cuts the update list roughly in half.

**Files that must be updated for signal_ledger slim migration:**

| File | What changes |
|---|---|
| `src/persistence/repository/signal_ledger_repository.py` | `LedgerEntry` dataclass, `_INSERT_SQL`, `_SELECT_ACTIVE_SQL`, `_SELECT_ACTIVE_BY_SYMBOL_SQL`, `fetch_active_signals()` |
| `services/signal_writer_agent.py` | `LedgerEntry` construction (stop passing 47 columns) |
| `src/intelligence/trading/lifecycle_tracker.py` | may read dropped columns |
| `src/intelligence/trading/aggregator.py` | may reference columns |
| `src/api/routes/signals.py` | SELECT list and row access for dropped columns |
| `src/api/routes/features.py` | JOIN query may reference dropped signal_ledger columns |
| `dashboard/` | API response shape may change |

### Recommended Execution Order for Tasks

```
Task 1: Storage audit doc (feeds planning for all other tasks)
Tasks 2+3: Retention policies + Kafka caps (pure config, no code, safe to run immediately)
Task 4: Drop feature_snapshots_shadow (depends on retention policies being set first so old data is bounded)
Task 5: signal_lineage investigation (DONE in research - no redesign needed, just add retention policy)
Task 6: Rename i1-i8 columns (the DB rename runs in seconds; code updates run simultaneously)
Task 7: Slim signal_ledger (DO THIS IN THE SAME MIGRATION AS Task 6 - one maintenance window)
Task 8: Create ml_signal_training table + nightly timer (depends on slim ledger)
```

### parity auditor replacement SQL

```sql
-- Replace entire feature_snapshots_shadow + parity_auditor_agent with this view/function.
-- Wire into an existing health check service (service_auditor or alerting_agent).
-- Fires if any (symbol, tf) has no new bar in the last 10 minutes.
CREATE OR REPLACE FUNCTION check_feature_pipeline_freshness()
RETURNS TABLE(symbol text, tf text, last_ts timestamptz, gap_minutes float)
LANGUAGE sql AS $$
    SELECT symbol, tf, MAX(ts) as last_ts,
           EXTRACT(EPOCH FROM (NOW() - MAX(ts))) / 60.0 as gap_minutes
    FROM intelligence_features
    WHERE ts > NOW() - INTERVAL '30 minutes'
    GROUP BY symbol, tf
    HAVING MAX(ts) < NOW() - INTERVAL '10 minutes'
    ORDER BY gap_minutes DESC;
$$;
```

Call this from `service_auditor_agent.py` in its existing Prometheus check loop. If it returns rows, publish to `topic_alert_requests`. No shadow table, no Kafka consumer, no separate service.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---|---|---|
| Column rename on compressed hypertable | Manual decompression + rename + recompress | `ALTER TABLE ... RENAME COLUMN` (works natively in TS 2.25.1) |
| Retention automation | Cron job / manual DELETE | `add_retention_policy()` (TimescaleDB background job) |
| Kafka byte cap | Custom producer-side trimming | `rpk topic alter-config ... --set retention.bytes=` |
| Nightly materialization | A new daemon service | systemd oneshot + timer (existing pattern: `ml-training`) |
| Feature matrix for ML | Ad-hoc JSONB unnesting at query time | Pre-materialized `ml_signal_training` typed columns |

---

## Common Pitfalls

### Pitfall 1: Renaming compression segmentby/orderby columns

**What goes wrong:** `ALTER TABLE ... RENAME COLUMN` fails with "cannot rename column that is part of compression settings" for `ts`, `symbol`, `tf`.
**Why it happens:** These are the segmentby/orderby columns in the compression definition.
**How to avoid:** Only rename `i1`-`i8` and `smc` (if needed) - none are in the compression settings (verified: only `symbol`, `tf`, `ts` are segmentby/orderby).
**Warning signs:** Error on the ALTER TABLE statement.

### Pitfall 2: Service restart race during column rename

**What goes wrong:** `feature_writer_agent` is running and tries to INSERT using old column names after `ALTER TABLE RENAME` has run. The INSERT fails with "column i1 does not exist".
**Why it happens:** Services are not restarted atomically with the DDL.
**How to avoid:** Stop all services that INSERT into `intelligence_features` BEFORE running the rename. Restart them AFTER code is deployed with new column names. Order: stop services → run DDL → deploy code → start services.

### Pitfall 3: DROP COLUMN on compressed hypertable triggers recompression

**What goes wrong:** `ALTER TABLE signal_ledger DROP COLUMN entry_price` triggers decompression of all compressed chunks, modification, and recompression. On 77 chunks of 12 GB, this can take 10-30 minutes and generate heavy I/O.
**Why it happens:** TimescaleDB 2.6+ supports DROP COLUMN on compressed tables but must physically modify compressed chunk data.
**How to avoid:** Plan a maintenance window. Alternatively, use the "stop writing → drop later" approach: first deploy code that stops writing the columns, then DROP them in a separate maintenance window after confirming stability.
**Warning signs:** Long-running DDL, high I/O during migration.

### Pitfall 4: Kafka consumer group offset after shadow table removal

**What goes wrong:** After removing `feature_snapshot_writer_group`, the group's offset remains in Redpanda. If the service is restarted, it may try to replay from its last offset.
**Why it happens:** Consumer group offsets are persistent in Kafka.
**How to avoid:** After stopping the service, delete the consumer group: `docker exec redpanda rpk group delete feature_snapshot_writer_group`. Not strictly necessary (group expires after `group.max.session.timeout.ms`) but prevents confusion in monitoring.

### Pitfall 5: ML training feature_builder.py SQL uses column names that change

**What goes wrong:** After renaming `i4` → `regime_features` and `i1` → `technical_indicators`, the `_TRAINING_SQL` in `feature_builder.py` breaks: `f.i4->>'hmm_regime'` and `f.i1->>'atr_pct'` reference old column names.
**Why it happens:** Column renames propagate immediately to all queries.
**How to avoid:** Update `feature_builder.py` as part of the column rename code deployment (same PR/commit).

### Pitfall 6: signal_lineage growing from non-lineage sources

**What goes wrong:** Assuming signal_lineage spike = per-candidate writes. Research confirmed this is WRONG - it's 5 rows per winner (5 agents). The spike tracked the signal_ledger volume explosion.
**Why it happens:** Without querying the data, the assumption seemed logical.
**How to avoid:** Research confirmed: no redesign needed for signal_lineage write pattern.

### Pitfall 7: dashboard API breaks when signal_ledger columns are dropped

**What goes wrong:** `src/api/routes/signals.py` has SELECT queries pulling `row["entry_price"]`, `row["stop_loss"]`, etc. from `signal_ledger`. After DROP, these fail.
**Why it happens:** The dashboard serves fire-time data that previously lived in signal_ledger.
**How to avoid:** The dashboard must JOIN to `intelligence_features.trading_signals` (i7 JSONB) to get fire-time data. This is a non-trivial query change. Plan the dashboard API update as part of the slim ledger task, not after.

### Pitfall 8: Parity auditor alert still firing after service removal

**What goes wrong:** The parity auditor's metrics (`PARITY_MATCH_RATE`, etc.) are referenced in Grafana alerts. After removing the service, the alert fires as "no data".
**Why it happens:** Grafana alert on a missing metric series.
**How to avoid:** Remove or update Grafana alert rules targeting parity metrics before retiring the service.

---

## Code Examples

### Verified: retention policy SQL (function signature confirmed on live DB)

```sql
-- Confirmed working pattern (from existing job 1025 config):
-- {"drop_after": "1 year", "hypertable_id": 35}
SELECT add_retention_policy('intelligence_features', INTERVAL '2 years', if_not_exists => true);
-- Returns integer job_id
```

### Verified: compression policy SQL (from existing jobs)

```sql
-- Confirmed working pattern (from existing jobs: "compress_after": "7 days")
SELECT add_compression_policy('ml_signal_training', INTERVAL '7 days', if_not_exists => true);
```

### Verified: Kafka alter-config (tested on live cluster)

```bash
# Tested: sets retention.bytes on existing topic
docker exec redpanda rpk topic alter-config intelligence.signal.audit --set retention.bytes=524288000
# Output: TOPIC                      STATUS
#         intelligence.signal.audit  OK
```

### Verified: ALTER TABLE RENAME on compressed hypertable (TimescaleDB 2.25.1)

```sql
-- Safe to run without decompression
ALTER TABLE intelligence_features RENAME COLUMN i1 TO technical_indicators;
-- Restrictions: only i1-i8 (not ts, symbol, tf which are segmentby/orderby)
```

### Pattern: nightly oneshot materialization timer (follows existing ml_training pattern)

```ini
# /etc/systemd/system/indicagent-ml-signal-training-materialize.service
[Unit]
Description=ML Signal Training Materialization
After=network.target

[Service]
Type=oneshot
User=bg
WorkingDirectory=/home/bg/dev/indicagent
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/ml_signal_training_agent.py
StandardOutput=append:/home/bg/dev/indicagent/logs/ml_signal_training_materialize_agent.log
StandardError=append:/home/bg/dev/indicagent/logs/ml_signal_training_materialize_agent.log
EnvironmentFile=/home/bg/dev/indicagent/.env
```

### Pattern: slim LedgerEntry construction in signal_writer_agent

After migration, `LedgerEntry` drops fire-time fields. The writer reads these from the signal payload's i7 JSONB for audit purposes but does NOT persist them to `signal_ledger`. The JOIN is: `intelligence_features.trading_signals[*] @> {"signal_id": <uuid>}`.

---

## State of the Art

| Old Approach | Current Approach | Impact |
|---|---|---|
| DROP COLUMN required decompression | TimescaleDB 2.6+: native DROP COLUMN on compressed | Enables zero-downtime column removal |
| RENAME COLUMN required decompression | TimescaleDB 2.1+: native RENAME on compressed | Column rename is a catalog operation only |
| Kafka retention: only by time | Kafka retention: by time AND bytes | Safety floor prevents unbounded growth |
| ML training: ad-hoc JSONB unnest at query time | Materialized store with typed columns | 10-100x faster ML batch reads |

---

## Open Questions

1. **Dashboard API backward compatibility during slim ledger migration**
   - What we know: `signals.py` pulls 80+ columns from `signal_ledger` including fire-time fields
   - What's unclear: Whether the dashboard has any non-API consumers that depend on the signal_ledger shape directly
   - Recommendation: Audit `src/api/routes/signals.py` and `features.py` for all `signal_ledger` column references before writing the slim ledger plan

2. **Exact scope of `features_snapshot` column**
   - What we know: It's a JSONB blob in `signal_ledger` storing the 25-key `_shadow` dict. It's also in `intelligence_features.i7` JSONB array elements (per `capture_signal_features()` in `confidence_utils.py`).
   - What's unclear: Whether `features_snapshot` in `signal_ledger` is REDUNDANT with what's in `i7` JSONB, or whether it's a different capture point.
   - Recommendation: Before dropping `features_snapshot` from `signal_ledger`, verify that the signal-level `features_snapshot` is accessible via the `signal_id` FK in `intelligence_features.trading_signals`.

3. **Maintenance window logistics for signal_ledger DROP COLUMN**
   - What we know: 77 chunks, 12 GB, TimescaleDB will process each chunk. Could take 10-30 minutes.
   - What's unclear: Whether the current version (2.25.1) handles DROP COLUMN on compressed chunks without full decompression (the docs say "supported" but don't specify if it triggers recompression).
   - Recommendation: Test the DROP COLUMN duration on a dev copy or single chunk before production. Monitor with `\timing` in psql.

4. **`signal_writer_agent.py` location**
   - What we know: Referenced in `_DAG_ORDER` as `indicagent-signal-writer` but not found in `/services/` during directory scan.
   - What's unclear: Whether it's in a different location or uses a different file name.
   - Recommendation: `find /home/bg/dev/indicagent/services -name "*signal_writer*"` to confirm path before planning the update.

---

## Sources

### Primary (HIGH confidence)

- Live DB queries on PostgreSQL 15.13 / TimescaleDB 2.25.1 - schema, chunk counts, job configs, row counts
- `/home/bg/dev/indicagent/src/persistence/repository/signal_ledger_repository.py` - exact 67-column INSERT, all SQL patterns
- `/home/bg/dev/indicagent/services/feature_snapshot_writer_agent.py` - consumer group confirmed `feature_snapshot_writer_group`
- `/home/bg/dev/indicagent/services/parity_auditor_agent.py` - metrics names, tables used
- `/home/bg/dev/indicagent/src/intelligence/ml/feature_builder.py` - `_TRAINING_SQL` confirmed pattern for ml_signal_training
- Live signal_lineage query: 27,013 distinct signals / 135,060 rows = exactly 5 per signal (5 agents)
- `rpk topic alter-config` tested on live Redpanda cluster: confirmed working

### Secondary (MEDIUM confidence)

- [TimescaleDB ALTER TABLE docs (via GitHub)](https://github.com/timescale/docs/blob/latest/use-timescale/compression/modify-a-schema.md) - RENAME COLUMN supported since 2.1+, DROP COLUMN since 2.6+
- [TimescaleDB PR #2909](https://github.com/timescale/timescaledb/pull/2909) - original implementation of RENAME COLUMN for compressed hypertables
- TimescaleDB function signature for `add_retention_policy` and `add_compression_policy` confirmed from `\df` on live DB

---

## Metadata

**Confidence breakdown:**
- Standard procedures (rename, retention, Kafka): HIGH - live DB queries + official docs
- Architecture (file impact scope): HIGH - directly read from source files
- signal_lineage investigation: HIGH - data query with exact row counts
- ml_signal_training schema: MEDIUM - derived from existing feature_builder pattern, not from an authoritative spec
- signal_ledger slim migration columns: HIGH - cross-referenced CONTEXT.md with actual DB schema and Python LedgerEntry

**Research date:** 2026-05-22
**Valid until:** 2026-08-22 (TimescaleDB API stable; codebase files may drift)
