# Storage Root Cause Fix

**Version:** 1.0
**Last Updated:** 2026-05-24
**Date:** 2026-05-24  
**Status:** Spec — pending plan  
**Addresses:** TOAST bloat on intelligence_features, signal_ledger recompression failure

---

## Problem Statement

PostgreSQL (TimescaleDB) volume grew from ~25 GB to ~48 GB in the past week despite Phase 104 adding retention and compression policies. Two structural root causes:

1. **intelligence_features TOAST bloat** — the current week's chunk is 17 GB: 225 MB heap + 16.7 GB TOAST. Autovacuumed recently (n_dead_tup = 0) but TOAST pages are bloated because `feature_writer_agent` does JSONB `||` UPDATEs on the `trading_signals` column after every bar for cross-asset symbols. Each UPDATE on a TOAST'd column creates a new TOAST entry; old ones accumulate as bloated pages autovacuum cannot reclaim fast enough. `n_tup_upd = 25,712` on the current chunk; 0 HOT updates (heap pages full, no room for in-place update).

2. **signal_ledger recompression permanently failing** — the May 14–21 chunk is 23 GB and cannot shrink. TimescaleDB tries to recompress every 12 hours; `lifecycle_writer_agent` is always doing lifecycle UPDATEs to signals from old chunks (signals stay active for days–weeks), so every recompression attempt aborts with "concurrent DML". 59 failures out of 198 total job runs.

---

## Root Causes (confirmed via data flow trace)

### Root Cause 1 — Wrong write pattern for cross-asset data

`feature_writer_agent._process_cross_asset_message()` consumes `topic_cross_asset` events from `cross_asset_compute_agent` (separate service, separate Kafka topic). It merges cross-asset market features (spread z-scores, correlation flags) into `trading_signals` via:

```sql
UPDATE intelligence_features
SET trading_signals = COALESCE(trading_signals, '{}'::jsonb) || $4::jsonb
WHERE ts = $1 AND symbol = $2 AND tf = $3
```

Two problems:
- **Wrong column**: `trading_signals` is the I7 output column (actual entry/exit signals). Cross-asset spread metrics are market context — they belong in `market_context`.
- **Wrong pattern**: Follow-up UPDATE on a TOAST'd column after initial INSERT causes uncontrolled TOAST churn. This fires for ES, NQ, RTY, YM × all active timeframes × every bar.

### Root Cause 2 — Mutable lifecycle state inside an append-optimised hypertable

`signal_ledger` is a TimescaleDB hypertable with compression. Its 62 columns include both immutable fire-time data (what was emitted) and mutable lifecycle state (what happened: activation, exit, PnL, shadow tracking, chandelier state). `signal_tracker_compute_agent` and `lifecycle_writer_agent` continuously UPDATE lifecycle columns on rows in old compressed chunks. TimescaleDB requires a write-quiet chunk to successfully recompress its decompressed tail — this never happens.

This is a fundamental incompatibility: compression is an append-only optimisation; lifecycle UPDATEs are inherently mutable.

---

## Fix A — Eliminate the cross-asset UPDATE path (cache-and-fold)

### Principle
Cross-asset data is group-level market regime context, updated every bar. The feature writer already has access to the full `BarIntelligenceRecord` at INSERT time. The fix: maintain a per-timeframe in-memory cache of the latest cross-asset snapshot in `FeatureWriterAgent`; fold it into the initial INSERT. Zero follow-up UPDATEs ever.

### Changes to `services/feature_writer_agent.py`

1. **Add `_cross_asset_cache: dict[str, dict]`** — keyed by timeframe, holds latest snapshot from `cross_asset_compute_agent`. Initialised as `{}` at startup.

2. **Rewrite `_process_cross_asset_message()`** — update `_cross_asset_cache[tf]` with incoming snapshot. No DB write. No `_UPDATE_I7_MERGE_SQL` call.

3. **Update `_record_to_insert_params()`** — merge `_cross_asset_cache.get(record.tf, {})` into the `market_context` JSONB parameter at INSERT time. Cross-asset keys (`cross_asset: {es_nq_spread_z, ...}`) live alongside existing market_context fields.

4. **Remove `_UPDATE_I7_MERGE_SQL` from the cross-asset path entirely.** Keep the constant only for the roll boundary path (fires ~2× per year per contract, negligible TOAST impact).

5. **Roll boundary** — the roll event writes `{"roll_boundary": "ESM6->ESU6"}` into `trading_signals` via the same UPDATE. This is rare but still semantically wrong. Move it to `market_context` and use the same UPDATE target. Net change: UPDATE hits `market_context` (avg 764 bytes, on-heap, no TOAST) instead of `trading_signals` (avg 3.4 kB, TOAST'd). PostgreSQL reuses existing TOAST pointers for all other columns — no TOAST churn.

### Data quality note
Cross-asset snapshot in the INSERT will be "latest available at write time" for the given timeframe, not the exact same-timestamp snapshot. For a market regime context feature computed over a 20-bar rolling window, sub-bar staleness has no analytical significance. This is the correct trade-off.

### Immediate remediation
After deploying Fix A: `VACUUM FULL intelligence_features` recovers the 15+ GB of TOAST bloat. Takes ~5–10 minutes with table lock; run during market close.

---

## Fix B — Split signal_ledger into immutable hypertable + signal_outcomes table

### Principle
Separate immutable fire-time data (what was emitted — never changes) from mutable lifecycle state (what happened — updates over time). The hypertable becomes append-only and compresses perfectly. Lifecycle state lives in a regular PostgreSQL table optimised for UUID-keyed point updates.

### New schema

#### `signal_ledger` (hypertable, INSERT-only, compress_after = 7 days)

Fire-time columns only — set at signal emission, never updated:

| Column | Type | Note |
|--------|------|------|
| signal_id | uuid | part of PK |
| timestamp | timestamptz | time dimension (hypertable) |
| symbol | text | |
| timeframe | text | |
| setup_plugin | text | |
| signal_type | text | |
| direction | int | |
| was_selected | bool | |
| is_shadow | bool | |
| is_backfill | bool | |
| signal_schema_version | text | |
| signal_computed_at | timestamptz | |
| feature_ts | timestamptz | |
| feature_tf | text | |
| hmm_regime_at_fire | int | point-in-time HMM regime |
| garch_sigma_at_fire | float8 | point-in-time GARCH σ |
| ttl_bars | int | |
| entry_price | numeric | |
| stop_loss | numeric | |
| targets | jsonb | |
| entry_zone_low | numeric | |
| entry_zone_high | numeric | |
| market_entry_price | float8 | Phase 1 price, set at emit |
| cis_score | float8 | |
| bucket_scores | jsonb | |
| weights_version | int | |
| pipeline_lag_ms | float8 | |

#### `signal_outcomes` (regular table, UUID-keyed, mutable)

All columns that are ever written by lifecycle UPDATEs:

| Column | Type | Note |
|--------|------|------|
| signal_id | uuid | PK, FK → signal_ledger.signal_id |
| status | text | default 'pending' |
| activated_at | timestamptz | |
| activation_price | float8 | |
| zone_entry_pct | float8 | |
| bars_to_activation | int | |
| exit_at | timestamptz | |
| exit_price | float8 | |
| exit_reason | text | |
| pnl_ticks | float8 | |
| pnl_r | float8 | |
| pnl_dollars | float8 | |
| signal_quality | float8 | |
| mae | float8 | |
| mfe | float8 | |
| bars_in_trade | int | |
| outcome | text | |
| market_entry_at | timestamptz | |
| market_entry_exit_price | float8 | |
| market_entry_exit_at | timestamptz | |
| market_entry_outcome | text | |
| market_entry_pnl_r | float8 | |
| market_entry_mae | float8 | |
| market_entry_mfe | float8 | |
| market_entry_bars_in_trade | int | |
| market_entry_gap_bars | int | |
| trailing_stop_price | jsonb | chandelier history |
| trailing_stop_tightening_rate | float8 | |
| staleness_score | float8 | |
| staleness_trigger_reason | text | |
| chandelier_vol_source | text | |
| shadow_tracking_start_ts | timestamptz | |
| shadow_mae | float8 | |
| shadow_mfe | float8 | |
| shadow_outcome | text | |
| effective_ts | timestamptz | |

#### `signal_ledger_full` (view)

```sql
CREATE VIEW signal_ledger_full AS
SELECT sl.*, so.status, so.activated_at, so.activation_price,
       so.zone_entry_pct, so.bars_to_activation,
       so.exit_at, so.exit_price, so.exit_reason,
       so.pnl_ticks, so.pnl_r, so.pnl_dollars, so.signal_quality,
       so.mae, so.mfe, so.bars_in_trade, so.outcome,
       so.market_entry_at, so.market_entry_exit_price, so.market_entry_exit_at,
       so.market_entry_outcome, so.market_entry_pnl_r, so.market_entry_mae,
       so.market_entry_mfe, so.market_entry_bars_in_trade, so.market_entry_gap_bars,
       so.trailing_stop_price, so.trailing_stop_tightening_rate,
       so.staleness_score, so.staleness_trigger_reason, so.chandelier_vol_source,
       so.shadow_tracking_start_ts, so.shadow_mae, so.shadow_mfe, so.shadow_outcome,
       so.effective_ts
FROM signal_ledger sl
LEFT JOIN signal_outcomes so ON sl.signal_id = so.signal_id;
```

Most SELECT consumers change `FROM signal_ledger` → `FROM signal_ledger_full` with no other query changes.

### Write path changes

**On new signal (signal_writer_agent → signal_ledger_repository.insert()):**
1. INSERT into `signal_ledger` (fire-time columns only)
2. INSERT into `signal_outcomes` (signal_id, status='pending', all others NULL)

Both inserts are atomic within one DB transaction.

**On lifecycle event (lifecycle_writer_agent → repository UPDATE methods):**
All UPDATE SQL changes from `UPDATE signal_ledger SET ... WHERE signal_id = $1` to `UPDATE signal_outcomes SET ... WHERE signal_id = $1`.

### Services requiring changes

| Service / File | Change type |
|---|---|
| `src/persistence/repository/signal_ledger_repository.py` | Major: rewrite INSERT SQL, all UPDATE SQL, LedgerEntry dataclass |
| `services/signal_writer_agent.py` | Minor: calls repository insert, picks up changes |
| `services/lifecycle_writer_agent.py` | Minor: calls repository update methods, picks up changes |
| `services/signal_tracker_compute_agent.py` | Read path: `FROM signal_ledger` → `FROM signal_ledger_full` |
| `services/signal_auditor_agent.py` | Read path: view swap + direct UPDATE calls |
| `services/shadow_auditor_agent.py` | Read path: view swap |
| `services/signal_metrics_compute_agent.py` | Read path: view swap |
| `services/graduation_compute_agent.py` | Read path: view swap |
| `services/swarm_ledger_writer_agent.py` | SELECT 1 existence check stays on signal_ledger; writes to signal_ai_enrichment only — no lifecycle writes |
| `services/signal_replay_auditor_agent.py` | Read path: view swap |
| `services/alpha_swarm_agent.py` | Read path: signal_lineage JOIN signal_ledger → view swap |
| `services/ml_discovery_agent.py` | Read path: intelligence_features JOIN signal_ledger → view swap |
| `services/ml_data_quality_agent.py` | Outcome coverage query must use signal_ledger_full (outcome lives in signal_outcomes) |
| `src/api/routes/signals.py` | Read path: view swap |
| `src/api/routes/narrative.py` | Read path: signal_ledger + intelligence_features JOIN → view swap |
| `production/scripts/lifecycle_replay.py` | Write path: replay must write to signal_outcomes |
| `production/scripts/historical_backfill.py` | Verify: bar backfill → pipeline → signal_writer → new schema |
| `production/scripts/compute_ic.py` | Read path: view swap |
| `production/scripts/check_validate_alpha_eligibility.py` | Read path: view swap |

### Migration approach (clean break — no prod data to preserve)

```
1. Stop all L6–L10 services (signal-writer, lifecycle-writer, signal-tracker, all writers)
2. DROP TABLE signal_ledger CASCADE  (also drops indexes, compression chunks, lineage FK)
3. DROP TABLE signal_outcomes IF EXISTS
4. Run migration SQL: CREATE signal_ledger + CREATE signal_outcomes + CREATE VIEW + indexes + hypertable + compression policy
5. Deploy updated code (all services above)
6. Start services
7. Run historical_backfill.py to regenerate bar → signal data
8. Lifecycle replay regenerates outcomes automatically as bars replay through the pipeline
```

No data migration required. `signal_lineage` references `signal_id` via FK — will be recreated by replay.

---

## Migration SQL file

New file: `production/migrations/095_signal_ledger_split.sql`

Recreates signal_ledger (fire-time only), creates signal_outcomes, creates signal_ledger_full view, re-adds hypertable setup and compression policy.

---

## Test requirements

- `signal_ledger_repository` unit tests: INSERT writes correct columns to each table; all UPDATE methods target signal_outcomes
- `lifecycle_writer_agent` unit tests: transitions write to signal_outcomes
- Integration: INSERT + lifecycle UPDATE + SELECT via view returns complete record
- Compression: after clean INSERT-only workload, chunk compresses without DML conflict
- TOAST regression: new intelligence_features rows do not create UPDATE-driven TOAST entries

---

## Expected outcomes

| Metric | Before | After |
|--------|--------|-------|
| intelligence_features TOAST (current chunk) | 17 GB | < 500 MB (heap only) |
| signal_ledger chunk recompression | 59/198 failures | 0 failures |
| Weekly storage growth | ~6 GB/day | ~200 MB/day |
| VACUUM FULL required | Yes (once, immediate) | No |
