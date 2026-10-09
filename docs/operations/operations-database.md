# Database — TimescaleDB Operations

**Version:** 2.10
**Last Updated:** 2026-10-08 (phase 185 section only)
**Status:** stale (v2.x, see banner)

---

> **Staleness note (2026-08-01):** This runbook's table list and commands target
> `intelligence_features`, `signal_ledger`, and `signal_outcomes` — ARCHIVED v2.x tables with
> no live consumer as of 2026-07-02 per CLAUDE.md. **The commands below target ARCHIVED
> tables — do not run against production without first verifying the target table still exists
> and is the live one** (`feature_vectors` is the current
> equivalent). Not yet rewritten for v3.0 -- tracked for a future doc pass, not fixed here.

## Purpose

TimescaleDB operations: tables, migrations, backfill, compression, backup, and advanced gotchas for IndicAgent's cold storage layer.

**Architecture:** Real-time pipeline never touches the database directly. Writers consume Kafka topics and persist to TimescaleDB: `indicagent-feature-writer`, `indicagent-signal-writer`, `indicagent-lifecycle-writer`, `indicagent-lineage-writer`, `indicagent-llm-writer`, `indicagent-swarm-ledger-writer`, `indicagent-signal-metrics-writer`.

---

## Tables

| Table | Purpose | Retention |
|-------|---------|-----------|
| `market_data_ohlcv` | Raw OHLCV — ground truth, never wipe | Forever |
| `intelligence_features` | Full feature vectors per bar (ML training dataset) | Forever |
| `signal_ledger` | I7 signals — fire-time fields | Forever |
| `signal_outcomes` | Mutable lifecycle fields (activation, exit, pnl_r) — JOIN via `signal_id` | Forever |
| `macro_features` | Macro/cross-asset feature vectors per bar | Forever |
| `llm_calls` | Full LLM audit log per call | Forever |
| `llm_model_scores` | Per-model win rate / avg pnl_r (refreshed 15min) | Forever |
| `setup_performance` | Per-setup rolling 30d stats (sample_size ≥ 30 gate) | Forever |
| `signal_lineage` | Swarm lineage events per signal | Forever |
| `signal_ai_enrichment` | Swarm aggregate adjustments | Forever |
| `shadow_registry` | Shadow governance enrollment + eval stats per plugin/agent | Forever |
| `cis_weights` | CIS calibration weights | Rebuilt nightly |
| `swarm_agent_weights` | Swarm agent performance weights | Rebuilt weekly |

**Never delete `market_data_ohlcv`.** Every bar is a labeled training sample. All downstream tables can be rebuilt from bar data via replay.

**Checkpoint files** (not DB): `cache/pipeline_checkpoint.json` (plugin states + Kalman), `cache/bar_replay_checkpoint.json` (live replay cursor). These are in-process state only — delete to force cold restart.

### Key Columns

| Table | Primary Time Column | Notes |
|-------|-------------------|-------|
| `market_data_ohlcv` | `timestamp` | Not `ts` |
| `intelligence_features` | `ts` | Not `feature_ts` |
| `signal_ledger` | `timestamp` | JOIN via `(symbol, feature_ts, feature_tf)` |
| `llm_calls` | `called_at` | Composite PK with `call_id` |

---

## Daily data foundation (phase 185, current as of 2026-10-08)

This section is current; the banner above applies to the rest of the file. Terms (observation,
canonical bar, scrub flag, quarantine, corporate action, listing venue, bar content digest,
derived grid) are defined in `docs/foundation/glossary.md`; owners are in
`docs/foundation/canonical-truth-registry.md`.

### Tables

| Table | Holds | Writer |
|-------|-------|--------|
| `ohlcv_request` | Every provider history request and its outcome (`bars`, `no_data`, `timeout`, `failed`, `legacy_import`), any timeframe, with route, `primary_exchange` and `caller` | `services/ohlcv_observation_writer.py` |
| `ohlcv_observation` | Every 1d bar answered (D1), per request, route (`SMART`, `NYSE`, `ARCA`, `ISLAND`, `AMEX`, `BATS`, `TRADIER`, `LEGACY_IMPORT`) and what_to_show | same |
| `ohlcv_load`, `ohlcv_revision` | The write record of every bar writer (ingress write contract, migration 448): one `ohlcv_load` row per series written, with `caller`, `destination` (`d1` or `market_data_ohlcv`), `batch_id`, `n_new`, `n_changed`, `n_unchanged`, `n_removed`; the old values of any bar a write changed in `ohlcv_revision`, with `origin` (`load`, `archive_segment`) | every bar writer through the contract (`bar_derivation` stages, the fetch paths) |
| `bar_source_policy` | Dated 1d source policy: per timeframe and per symbol exception, `[valid_from, valid_to)`, `ingress_mode`, `primary_source`, `fallback_source`, reason, evidence | `scripts/ops/bars/ops_source_policy.py` |
| `market_data_ohlcv` | Canonical bars, real rows only (no `synthetic_fill` since 185-25). 1d: `tradier`, `ibkr_fallback` or `ibkr_named` by policy (d2-v2); 15m/1h: `derived_5m`; 5m/1m: provider bars | 1d, 15m, 1h: `bar_derivation`; 5m/1m: the IBKR history fetcher |
| `ohlcv_coverage` | Per (symbol, timeframe) bounds, row count and last fetch status: the fetcher's ranking cache, derived and rebuildable (`--rebuild-coverage`) | the IBKR history fetcher |
| `integrity_monitor` (`monitor_type = 'bar_integrity'`) | D7 verdict rows, subject `SYM\|tf`, one per check; the promotion and rebuild gate reads them (`verdict_gate.py`) | `services/bar_reconciliation_audit.py` |
| `canonical_bar_lineage` | View (migration 447): which observation each canonical 1d bar equals, derived on read | none (a view) |
| `ohlcv_intraday_raw_archive` | The IBKR 15m/1h answers the derived grid replaced (hypertable) | `bar_derivation --stage grid` |
| `bar_quality_flag` | Scrub flags; `quarantine = true` hides the bar | `bar_scrub` (via the daily stage), `bar_derivation` |
| `corporate_action` | Splits and reverse splits, append-only, `supersedes` and `void` for corrections | split detect (`ops_split_detect.py`: the nightly overlap and its sanctioned corrections); `tradier_refetch` rows (the Tradier loader, deleted in 185-48) and seam audit rows are history |
| `listing_venue` | Point-in-time listing venue spans per symbol (D6) | `services/listing_venue_writer.py` (manual run) |
| `bar_content_digest` | Per (symbol, timeframe, month) checksum, append-only | `bar_derivation` |
| `bar_derivation_batch` | One row per derivation-side run: stage, rule version, code commit, APR snapshot | every derivation-side writer |
| `ohlcv_empty_history` | Spans every required route answered no_data for | the fetch helpers (`_empty_history.py`) |

The fetch bookkeeping table was dropped by migration 459 (plan 185-43); progress is
`ohlcv_coverage` and promotion reads verdicts. D1 tables are plain tables (not hypertables). `ohlcv_request` and `ohlcv_observation` are mutable
since migration 438; `corporate_action`, `bar_content_digest` and `listing_venue` refuse rewrites
in a trigger (superuser included).

### Roles

Both writer roles are `NOLOGIN`; the `postgres` login narrows itself with
`SET LOCAL ROLE <role>` inside each write transaction, so grants are the fence.

- `ohlcv_observation_writer`: INSERT (and since 438 UPDATE, DELETE) on the D1 tables.
- `bar_derivation_writer`: DML on `market_data_ohlcv` and the derivation side tables; read-only on
  D1; INSERT and `UPDATE (valid_to)` only on `listing_venue`.

### Views

- `market_data_ohlcv_tradeable`: `volume > 0` and no quarantine flag. Every research and compute
  read goes through it (`tests/unit/test_market_data_ohlcv_boundary.py`).
- `market_data_ohlcv_scrub_input`: every traded bar, quarantined included; the scrub stage's
  input.
- `corporate_action_current`, `bar_content_digest_current`: rows nothing later supersedes.
- `ohlcv_venue_head`: per (symbol, route) first and last venue bar and the SMART head;
  `pre_move` marks venue history before the head (the moved-name inventory). It also lists
  the `TRADIER` route; filter routes to the venue list.

Readers of D1 exclude rows a test wrote: `ohlcv_request.caller NOT LIKE 'test-%'` (todo 494).

### Daily data chain

Two units replace the nightly backfill script, which plan 189-07 deleted. The 1d source is
chosen per date by `bar_source_policy`: Tradier before D = 2026-10-07 (its bars stay canonical
history; the account is not funded and plan 185-48 deleted its loader, units and provider),
IBKR SMART TRADES from D (migration 456), and per-symbol exception rows (MOD and QRVO keep
Tradier primary through hold rows).

1. `indicagent-ibkr-history-fetcher.timer` (every 15 min after the last run ends; disabled
   until plan 189-10 by owner decision 2026-10-06) runs
   `scripts/infrastructure/backfill/ibkr_history_fetcher.py`: the `ohlcv_coverage` queue over
   APR `infra.backfill.default_scopes` in two lanes, the update lane (every active name's 1d
   and 5m since its latest stored bar, overlapping the stored tail) and the gap-fill lane (a
   series' full depth once every `infra.backfill.gap_fill_interval_days`), then at run end split
   detection (`ops_split_detect.py`), the daily stage (`bar_derivation --stage daily`: D2
   canonical 1d plus the D2a scrub rules) and the grid stage (`bar_derivation --stage grid
   --changed-only --apply`: D2b 15m/1h), then the status file
   `logs/ibkr_history_fetcher_status.json` (D7's `nightly_skipped` reads it) and
   `job_completed_total`.
2. `indicagent-bar-reconciliation-audit.timer` (06:00 UTC) runs the D7 audit
   (`services/bar_reconciliation_audit.py`).

D7 checks (findings go to `integrity_monitor` and OTel, never the exit code):
`route_disagreement`, `adjusted_vs_trades`, `daily_vs_intraday`, `unexplained_seams`,
`late_heads`, `listing_venue_coverage`, `unconfirmed_empty`, `partial_daily`,
`dividend_freshness`, `nightly_skipped`, `stray_sources`, `switches`, `completeness`,
`masked_slots`, `held_names`, plus vendor agreement per year (Tradier against IBKR SMART over
the stored overlap; Tradier ends at 2026-10-06, so the table is constant and stays for the
operations dashboard). It also writes the verdict
report: one `bar_integrity` row per (symbol, timeframe, check) for the 1d checks
(session_coverage, policy_conformance, lineage_missing, canonical_recompute, digest_fresh,
unexplained_seam, vendor_basis_run, freshness_1d) and the intraday checks (slot_coverage,
digest_fresh, coverage_cache, grid_parity, stray_vendor_rows). Promotion and the phase 186
rebuild pass only on passed, fresh verdicts (`src/intelligence/bars/verdict_gate.py`).

Grafana rules on these gauges: `bar_integrity_failing`, `bar_integrity_report_stale`,
`bar_freshness_1d` (a name more than `threshold.bar_integrity.freshness_max_lag_sessions_1d`
sessions behind), `ibkr_fetcher_sla_breached` and `revision_refused` (ibkr and derived loads
refused or gated in the last 24 h).

Not in the chain: `services/listing_venue_writer.py` (run after an onboarding batch is
promoted; append-only, idempotent).

---

## Primary key inventory (D-37, phase 186)

Rule: **every new table carries a primary key**. On hypertables the PK must include
the time (partition) column; Timescale 2.27.1 cannot convert an existing index into
a constraint on a hypertable (`ADD CONSTRAINT ... USING INDEX` errors with
"hypertables do not support adding a constraint using an existing index"), so a
declared PK has to be planned at table creation, not retrofitted cheaply. A UNIQUE
index over all-NOT-NULL columns including the time column is functionally
equivalent (dedup, `ON CONFLICT` resolution) and is the one standing exception:

- `market_data_ohlcv` — `market_data_ohlcv_pkey_idx` UNIQUE ("timestamp", symbol,
  timeframe), all columns NOT NULL, includes the partition column. Declared the
  recorded PK-equivalent exception (design 14.5, migration 193's verified-working
  form; converting the 674M-row compressed hypertable is not worth a second
  full-size blocking rebuild).

Inventory taken 2026-09-28 (migration 385): every public table then lacking a PK,
and its disposition.

| Table | Disposition |
|---|---|
| `ctx_events` | Dropped by 186-11 (owner of the writer) |
| `feature_ic_scores_history` | Dropped by 186-22 (old chain) |
| `market_data_ohlcv` | Kept: unique-index PK equivalent (exception above) |
| `dlq_events` | `PRIMARY KEY (id, routed_at)`; `dlq_events_dedup_idx` remains the `ON CONFLICT` target |
| `integrity_monitor` | `PRIMARY KEY (id, evaluated_at)`; expression unique index remains the `ON CONFLICT` target |
| `drift_monitor` | Dropped (migration 385): empty, no code writer or reader |
| `alpha_multiplier_shadow` | `id` IDENTITY + `PRIMARY KEY (id, ts)` |
| `service_health_events` | `id` IDENTITY + `PRIMARY KEY (id, ts)` |
| `signal_lineage` | `id` IDENTITY + `PRIMARY KEY (id, ts)` |
| `signal_transform_log` | `id` IDENTITY + `PRIMARY KEY (id, ts)` |
| `transform_graduation` | `PRIMARY KEY (transform_id, transform_version, segment_key)` replacing the former unique constraint |

Adding a column with a default (the identity `id`) cannot break writers because
every INSERT into these tables names its columns (verified by grep before the
migration). A surrogate `(id, time)` PK is unique by construction: the sequence
makes `id` distinct even for identical logical rows.

---

## Connection

```bash
# From host
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent

# From Docker
docker exec -it timescaledb psql -U postgres indicagent

# Common queries
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "<query>"
```

---

## Migrations

Migrations live in `production/migrations/` and are numbered sequentially.

### Apply all migrations (first-time setup)

```bash
bash scripts/infrastructure/setup/infrastructure_db_setup.sh
```

### Apply a single migration

```bash
# Method 1: Direct
docker exec timescaledb psql -U postgres -d indicagent -f /path/to/migration.sql

# Method 2: Via docker cp (for complex migrations)
docker cp file.sql timescaledb:/tmp/file.sql
docker exec timescaledb psql -U postgres -d indicagent -f /tmp/file.sql
```

**Gotcha:** `docker exec timescaledb psql ... -f /dev/stdin <<'EOF'` does NOT work. Always copy the file first.

### Migration version

```sql
SELECT version FROM schema_migrations ORDER BY applied_at DESC LIMIT 1;
```

---

## Backfill and Gap-Fill

> One IBKR history stream: `scripts/infrastructure/backfill/ibkr_history_fetcher.py`
> (`indicagent-ibkr-history-fetcher`, phase 189) works the `ohlcv_coverage` queue under its
> singleton lock. The todo 449 lane scripts under `logs/backfill_ops/` were deleted in plan
> 189-07. Concurrent history streams measured no added throughput (todo 449, 2026-09-27) and
> contend for the same pacing budget.

### Full pipeline reset (reset_pipeline_data.py)

Wipes all intelligence-derived tables and re-runs full fetch + replay. Use when signal logic, stop/target geometry, or lifecycle logic changes substantially enough that historical P&L is no longer trustworthy.

```bash
# Dry run — prints row counts, exits without touching data
python scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py

# Full reset: wipe + fetch + replay (stop pipeline first)
sudo systemctl stop indicagent-intelligence-pipeline
python scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py --confirm

# Wipe only — skip re-fetch and replay
python scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py --confirm --wipe-only

# More workers for faster replay
python scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py --confirm --workers 8
```

**Tables wiped** (bar data preserved): `intelligence_features`, `signal_ledger`, `signal_outcomes`, `signal_lineage`, `signal_transform_log`, `signal_metrics*`, `signal_ai_enrichment`, `macro_features`, `llm_calls`, `llm_model_scores`, `setup_performance`, `swarm_agent_weights`, `cis_weights`, `tod_multipliers`, `confidence_calibration`, `calibration_curves`, `drift_state`, `pattern_reliability`, `transform_graduation`, `ml_discovery_runs`, `memory_*`. (`drift_monitor` was dropped 2026-09-28, migration 385 — empty, no code writer.) Shadow registry enrollment kept; eval stats reset.

### Lifecycle replay (lifecycle_replay.py)

Evaluates signal outcomes for all signals that lack them, by replaying `market_data_ohlcv` bars chronologically. Run after any full replay to compute pnl_r, mae, mfe, exit_reason.

```bash
# Normal run — fills in missing outcomes only
python -u scripts/debug/replay/debug_lifecycle_replay.py --workers 8

# Reset + replay (for corrupt outcomes — stop pipeline first)
sudo systemctl stop indicagent-intelligence-pipeline
python -u scripts/debug/replay/debug_lifecycle_replay.py --reset --confirm --workers 8

# Dry run to verify schema compatibility
python -u scripts/debug/replay/debug_lifecycle_replay.py --symbols ESM6 --timeframes 5m --dry-run

# Specific symbols only
python -u scripts/debug/replay/debug_lifecycle_replay.py --reset --confirm --symbols ESM6,NQM6
```

**After replay:** `setup_performance` and `swarm_agent_weights` are empty — they repopulate on next scheduled runs (nightly ml-training at 11pm; weekly ml-orchestrator on Monday).

### Gap-fill after downtime

Fetches only the missing recent bars and replays only that window. Safe — `ON CONFLICT DO NOTHING` means existing rows are never touched.

```bash
# Step 1: Fetch missing OHLCV bars
.venv/bin/python scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py \
  --fetch-only --symbols EURUSD,BTCUSD --days 2

# Step 2: Replay only those 2 days through I1→I7
.venv/bin/python scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py \
  --replay-only --symbols EURUSD,BTCUSD --days 2
```

### Default TF fetch depths

| TF | Depth | Contract |
|----|-------|---------|
| 1m | 14 days | Named |
| 5m | 90 days | Named (chunked) |
| 15m | 180 days | Continuous adjusted |
| 1h | 365 days | Continuous adjusted |
| 1d | 2555 days (7yr) | Continuous adjusted |

### Full replay without re-fetching OHLCV

Re-runs I1→I7 from existing DB bars.

```bash
# Idempotent — only fills gaps
.venv/bin/python scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py --replay-only --symbols SYM,SYM

# Clean re-generate — deletes existing signals then replays
.venv/bin/python scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py --replay-only --clean --symbols SYM,SYM
```

---

## Compression

Chunks older than 7 days are compressed automatically. Compression reduces storage 80–95%.

### Check compression status

```sql
SELECT hypertable_name, total_chunks, number_compressed_chunks
FROM timescaledb_information.hypertable_compression_stats;
```

### Manually compress

```sql
-- After large backfill
SELECT compress_chunk(c)
FROM show_chunks('intelligence_features', older_than => INTERVAL '7 days') c;
```

### Bulk UPDATE on compressed data

Decompresses chunks by default and can hit tuple limits. Disable limit for large updates:

```sql
SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0;
-- then run your UPDATE
```

### `CREATE INDEX CONCURRENTLY`

Not supported on hypertables — omit `CONCURRENTLY`.

### Recompress after backfill

After any large backfill, check for anomalously large compressed chunks:

```sql
SELECT chunk_name, pg_size_pretty(total_bytes)
FROM timescaledb_information.chunks
WHERE hypertable_name = 'market_data_ohlcv'
ORDER BY total_bytes DESC
LIMIT 10;

-- Recompress a specific chunk
CALL recompress_chunk('_timescaledb_internal._hyper_1_42_chunk');
```

---

## VACUUM

Cannot run inside a transaction block. Use standalone command:

```bash
docker exec timescaledb psql -U postgres -d indicagent -c "VACUUM ANALYZE intelligence_features;"
```

### Autovacuum on hypertables

`ALTER TABLE` settings only apply to the parent, not existing chunks. To cover all chunks:

```sql
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT chunk_schema, chunk_name FROM timescaledb_information.chunks
           WHERE hypertable_name = 'intelligence_features' AND hypertable_schema = 'public'
  LOOP
    EXECUTE format('ALTER TABLE %I.%I SET (autovacuum_vacuum_scale_factor = 0.01)', r.chunk_schema, r.chunk_name);
  END LOOP;
END $$;
```

**Important:** Use `record` type (not `text`) to avoid ambiguous column name conflicts with `chunk_name`.

### TRUNCATE Behavior

`TRUNCATE` removes all chunks — after `TRUNCATE`, `timescaledb_information.chunks` returns 0 rows. Autovacuum settings on parent automatically apply to all future chunks.

`set_chunk_time_interval()` applies to new chunks only — best done while table is empty after TRUNCATE:

```sql
TRUNCATE your_table;
SELECT set_chunk_time_interval('your_table', INTERVAL '1 month');
```

---

## Performance Analysis

### Slow query analysis

`pg_stat_statements` is enabled:

```sql
SELECT calls, round(mean_exec_time::numeric, 2) AS mean_ms, query
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 10;
```

### Parallel query errors in Docker

```sql
SET max_parallel_workers_per_gather = 0;
```

### Index usage

`pg_stat_user_indexes.idx_scan` is always 0 for hypertable parents — chunk-level indexes are tracked separately. Never use idx_scan=0 to identify unused indexes on hypertables.

### Table size

`pg_total_relation_size()` returns near-zero for hypertable parents. Use:

```sql
SELECT pg_size_pretty(hypertable_size('market_data_ohlcv'));
```

### Row count estimates

`COUNT(*)` locks all chunks on multi-chunk hypertables. Use `reltuples` for estimates:

```sql
SELECT reltuples::bigint FROM pg_class WHERE relname = 'market_data_ohlcv';
```

---

## Backups

**Do NOT use `pg_dump` for hypertables** — chunks do not restore cleanly. Use raw Docker volume copy:

```bash
# Stop container first
docker stop timescaledb

# Copy volume
docker run --rm \
  -v production_timescale-data:/src:ro \
  -v backup_timescale-data:/dst \
  alpine sh -c "cd /src && cp -a . /dst/"

# Start container
docker start timescaledb
```

### Schema-only dump

If you must use `pg_dump` (schema only, or non-hypertable data), always redirect stderr separately — `pg_dump ... 2>&1` corrupts `--Fc` binary output:

```bash
pg_dump -U postgres -h localhost -d indicagent -Fc -f backup.dump 2>dump_errors.log
```

---

## Compression Settings Verification

`compression_enabled=true` ≠ policy exists. Verify:

```sql
SELECT hypertable_name, config
FROM timescaledb_information.jobs
WHERE application_name LIKE 'Columnstore%';
```

---

## Materialized Views

`signal_stats_daily` is a materialized view — appears in `pg_stat_user_tables` but cannot be TRUNCATEd. Use:

```sql
REFRESH MATERIALIZED VIEW signal_stats_daily;
```

`signal_ledger_full` is a view (joins `signal_ledger` + `signal_outcomes`) — cannot be TRUNCATEd. Query it for full lifecycle state; write to the underlying tables directly.

---

## Hypertable Migration

Never use `pg_dump/restore` for hypertables — chunks do not restore cleanly. Use raw volume copy:

```bash
docker run --rm -v old-vol:/src:ro -v new-vol:/dst alpine sh -c "cd /src && cp -a . /dst/"
```

---

## Freshness Checks

```bash
# Latest OHLCV bars
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT symbol, tf, MAX(timestamp) as last_bar FROM market_data_ohlcv \
   GROUP BY symbol, tf ORDER BY last_bar DESC LIMIT 5"

# Latest features
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT symbol, tf, MAX(ts) as last_feature FROM intelligence_features \
   GROUP BY symbol, tf ORDER BY last_feature DESC LIMIT 5"

# Latest signals
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT symbol, timeframe, MAX(timestamp) as last_signal FROM signal_ledger \
   GROUP BY symbol, timeframe ORDER BY last_signal DESC LIMIT 5"
```

---

## See Also

- **Infrastructure:** `docs/operations/operations-infrastructure.md` — Docker, systemd
- **Observability:** `docs/operations/operations-observability.md` — Metrics, dashboards
- **Migrations:** `production/migrations/` — Migration scripts
