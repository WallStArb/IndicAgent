# Database — TimescaleDB Operations

**Version:** 2.11
**Last Updated:** 2026-10-27 (bar data layer and backfill sections only)
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

## Bar data layer (phases 185 and 191, current as of 2026-10-27)

This section is current; the banner above applies to the rest of the file. Terms (observation,
canonical bar, scrub flag, quarantine, corporate action, listing venue, bar content digest,
derived grid) are defined in `docs/foundation/glossary.md`; owners are in
`docs/foundation/canonical-truth-registry.md`.

### Tables

| Table | Holds | Writer |
|-------|-------|--------|
| `ohlcv_request` | Every provider history request and its outcome (`bars`, `no_data`, `timeout`, `failed`, `legacy_import`), any timeframe, with route, `primary_exchange` and `caller` | `services/ohlcv_request_writer.py` |
| `ohlcv_raw` | The single raw store of vendor answers (todo 533): every bar a supplier served, under its `(vendor, kind)` label, one row per (symbol, timeframe, vendor, kind, timestamp), any timeframe | `services/ohlcv_raw_writer.py` (single writer) |
| `ohlcv_load`, `ohlcv_revision` | The write record of every bar writer (ingress write contract, migration 448; raw-first since phase 191): one `ohlcv_load` row per series written, with `caller`, `destination` (`raw` or `market_data_ohlcv`; `d1` and `archive` on older rows), `batch_id`, `n_new`, `n_changed`, `n_unchanged`, `n_removed`, `n_superseded`; the old values of any bar a write replaced in `ohlcv_revision`, with `origin` (`raw`, `superseded`; `load`, `archive_segment` on older rows). Both are permanent lineage | every bar writer through the contract (`bar_derivation` stages, the fetch paths, the load engine) |
| `bar_source_policy` | Dated source policy per timeframe and per symbol exception, `[valid_from, valid_to)`, `ingress_mode`, `primary_source`, `fallback_source`, reason, evidence; a row is closed or retired (migration 520), never edited. Read through `bar_source_policy_current` (live rows; a guard test forbids reading the table) | `scripts/ops/bars/ops_source_policy.py` |
| `market_data_ohlcv` | Canonical bars, real rows only (no `synthetic_fill` since 185-25), labeled `vendor` and `kind`. 1d: `(tradier, consolidated)`, `(ibkr, fallback)` or `(ibkr, named)` by policy (rule d2-v3); 5m: `(alpaca, sip_rth)` from 2016-01-04 and `(ibkr, named)` by policy (D-191-P); 15m/1h: `(derived, 5m_grid)` | 1d, 15m, 1h: `bar_derivation`; 5m, 1m, 4h: `services/bar_selection.py`, called by the ingress contract after each raw write |
| `bar_session_choice` | One row per non-trivial 5m/1m/4h session choice (a fallback session, a session no vendor holds completely), migration 480 | `services/bar_selection.py` |
| `ohlcv_coverage` | Per (symbol, timeframe, provider) bounds, row count and last fetch status: the fetcher's ranking cache, derived and rebuildable (`--rebuild-coverage`) | the fetch paths (`services/ohlcv_coverage_writer.py`) |
| `listing_end` | A name's recorded last session after a merger, buyout or delisting (migration 518); `freshness_1d` judges the name up to it. Read `listing_end_current` | migration only |
| `integrity_monitor` (`monitor_type = 'bar_integrity'`) | D7 verdict rows, subject `SYM\|tf`, one per check; the promotion and rebuild gate reads them (`verdict_gate.py`) | `services/bar_reconciliation_audit.py` |
| `canonical_bar_lineage` | View (migration 447): which stored vendor bar each canonical 1d bar equals (`ohlcv_raw` joined to `ohlcv_request`), derived on read | none (a view) |
| `bar_quality_flag` | Scrub flags; `quarantine = true` hides the bar | `bar_scrub` (via the daily stage), `bar_derivation` |
| `corporate_action` | Splits and reverse splits, append-only, `supersedes` and `void` for corrections | split detect (`ops_split_detect.py`: the nightly overlap and its sanctioned corrections); `tradier_refetch` rows (the Tradier loader, deleted in 185-48) and seam audit rows are history |
| `listing_venue` | Point-in-time listing venue spans per symbol (D6) | `services/listing_venue_writer.py` (manual run) |
| `bar_content_digest` | Per (symbol, timeframe, month) checksum, append-only | `bar_derivation` |
| `bar_derivation_batch` | One row per derivation-side run: stage, rule version, code commit, APR snapshot | every derivation-side writer |
| `ohlcv_empty_history` | Spans every required route answered no_data for | the fetch helpers (`_empty_history.py`) |

The fetch bookkeeping table was dropped by migration 459 (plan 185-43); progress is
`ohlcv_coverage` and promotion reads verdicts. `ohlcv_observation` and
`ohlcv_intraday_raw_archive` were dropped by migration 499 (plan 191-16): plan 191-05 had moved
every write to `ohlcv_raw` and plans 191-13 and 191-16 proved the canonical output equal, so the
stores they replaced were dead weight. A COPY backup of both (218,252,126 rows, 50 gzip slices
with sha256 in `old_store_backup_manifest.json`) sits in `data/backups/191/`, retained until
2026-11-12; `scripts/ops/bars/ops_old_store_backup.py --verify-files` checks it against its
manifest without a database. The fetch-ledger and raw tables are plain tables (not hypertables).
`ohlcv_request` is mutable since migration 438; `corporate_action`, `bar_content_digest` and
`listing_venue` refuse rewrites in a trigger (superuser included).

Tradier (not funded since 2026-10-07; nothing answered after 2026-10-06): plan 191-20 deletes
its bar rows (`ohlcv_raw` and canonical vendor `tradier`, its `ohlcv_revision` rows, its
`ohlcv_coverage` rows) after the owner approves the residue report, with a COPY backup in
`data/backups/191/` kept until about 2026-11-12. Its `ohlcv_request` and `ohlcv_load` rows stay
as lineage. Until then its history is canonical 1d before 2026-10-07.

### Roles

Both writer roles are `NOLOGIN`; the `postgres` login narrows itself with
`SET LOCAL ROLE <role>` inside each write transaction, so grants are the fence.

- `ohlcv_observation_writer`: SELECT, INSERT, UPDATE and DELETE on `ohlcv_request` (plus SELECT
  on `instruments`); the name outlives the 191-16 drop of its old tables (a role rename is a
  migration with no benefit) and its live user is `services/ohlcv_request_writer.py`.
- `bar_derivation_writer`: DML on `market_data_ohlcv` and the derivation side tables; read-only on
  the raw layer; INSERT and `UPDATE (valid_to)` only on `listing_venue`.

### Views

- `market_data_ohlcv_tradeable`: `volume > 0` and no quarantine flag. Every research and compute
  read goes through it (`tests/unit/test_market_data_ohlcv_boundary.py`).
- `market_data_ohlcv_scrub_input`: every traded bar, quarantined included; the scrub stage's
  input.
- `corporate_action_current`, `bar_content_digest_current`: rows nothing later supersedes.
- `ohlcv_venue_head`: per (symbol, route) first and last venue bar and the SMART head;
  `pre_move` marks venue history before the head (the moved-name inventory). It also lists
  the `TRADIER` route; filter routes to the venue list.

Readers of the raw layer exclude rows a test wrote: `ohlcv_request.caller NOT LIKE 'test-%'`
(todo 494).

### Nightly bar chain

Four timers. Sources are chosen per date by `bar_source_policy_current`:

- 1d today: Tradier before D = 2026-10-07 (closed default row, IBKR fallback), IBKR SMART
  TRADES from D (migration 456), and per-symbol exception rows (MOD and QRVO keep Tradier
  primary through hold rows). Decided, lands with plan 191-20 (todo 545): D-191-Q makes Alpaca
  SIP the 1d primary from 2016-01-04 with IBKR fallback only where Alpaca has no tradeable bar,
  IBKR alone before; a zero-volume bar never serves; spin-off and ticker-reuse exceptions are
  per-name rows from a one-time three-vendor arbitration (Alpaca, IBKR, Tradier) before
  Tradier is deleted, and spans where all three disagree go to the owner.
- 5m (D-191-P, done 2026-10-27): Alpaca SIP (`sip_rth`) from 2016-01-04 with IBKR fallback,
  IBKR alone before. `iex_rth` is raw only and never selected.

1. `indicagent-ibkr-history-fetcher.timer` (enabled; every 15 min after the last run ends) runs
   `scripts/infrastructure/backfill/ohlcv_history_fetcher.py` under `FetcherLock`: the
   `ohlcv_coverage` queue over
   APR `infra.backfill.default_scopes` in two lanes, the update lane (every active name's 1d
   and 5m since its latest stored bar, overlapping the stored tail) and the gap-fill lane (a
   series' full depth once every `infra.backfill.gap_fill_interval_days`), then at run end split
   detection (`ops_split_detect.py`), the daily stage (`bar_derivation --stage daily`: D2
   canonical 1d plus the D2a scrub rules) and the grid stage (`bar_derivation --stage grid
   --changed-only --apply`: D2b 15m/1h), then the status file
   `logs/ibkr_history_fetcher_status.json` (D7's `nightly_skipped` reads it) and
   `job_completed_total`.
2. `indicagent-alpaca-nightly.timer` (04:40 UTC) runs `scripts/ops/bars/ops_bar_nightly.py
   --vendor alpaca --apply`: every active name's recent 5m and 1d SIP window
   (`infra.alpaca.nightly_window_days`), ending `infra.alpaca.sip_recent_lag_minutes` (20)
   before now because the free plan refuses recent SIP, bounded by
   `infra.alpaca.nightly_max_requests` and `infra.alpaca.nightly_deadline_minutes`. 5m is
   selected into canonical in the same transaction; 1d is raw capture only.
3. `indicagent-bar-derivation-grid.timer` (05:45 UTC) runs `bar_derivation --stage grid
   --changed-only --apply`, deriving 15m/1h from the night's 5m.
4. `indicagent-bar-reconciliation-audit.timer` (06:00 UTC) runs the D7 audit
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
unexplained_seam, alpaca_basis_run, freshness_1d) and the intraday checks (slot_coverage,
digest_fresh, coverage_cache, grid_parity, stray_vendor_rows). Promotion and the phase 186
rebuild pass only on passed, fresh verdicts (`src/intelligence/bars/verdict_gate.py`).

`coverage_cache` rebuilds the coverage ledger under the IBKR history fetcher lock. The fetcher
runs in windows of several hours with a 15 minute gap, so the audit polls the non-blocking
try-lock every `infra.bar_integrity.coverage_cache_lock_poll_s` (30 s) for up to
`infra.bar_integrity.coverage_cache_lock_wait_s` (21600 s) and runs the check as the last step of the
run, after every other verdict is written and with no pool connection held. If the lock is still
held at the bound, the check is skipped, logged (`bar_integrity.coverage_cache_skipped`) and
counted in `coverage_cache_skipped`; a skipped check writes no row, so the verdict ages out of the
30 h freshness the rebuild gate requires.

`grid_parity` re-buckets canonical 5m bars into the IBKR archive's 15m/1h buckets and requires
exact equality, but only on buckets whose 5m constituents are all `vendor = 'ibkr'`. Since D-191-P
the 5m from 2016-01-04 is Alpaca SIP, which legitimately differs from the IBKR reference, so those
buckets are excluded like a bucket one side lacks. The verdict metric is the mismatched count;
`NULL` means no bucket was comparable (a pass that measured nothing), and the run log carries
`grid_parity_compared_nothing`, `grid_parity_buckets_compared` and `grid_parity_buckets_mismatched`
per timeframe.

Grafana rules on these gauges: `bar_integrity_failing`, `bar_integrity_report_stale`,
`bar_freshness_1d` (a name more than `threshold.bar_integrity.freshness_max_lag_sessions_1d`
sessions behind, judged only up to a recorded `listing_end`), `ibkr_fetcher_sla_breached` and
`revision_refused` (refused derived loads plus unreviewed basis-change restatement flags; vendor
loads are never refused, D-191-N).

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

## Postgres settings (D-38, phase 186)

`production/docker-compose.yml` (the timescaledb service's `command:` list and
`shm_size`) is the **only** place server settings are set. Never `ALTER SYSTEM`,
never a role- or database-level override: those hide from the compose file and
reappear as drift. Current values, applied 2026-10-11 (commit 29f507735):

| Setting | Value | Formula and inputs |
|---|---|---|
| `shared_buffers` | 7GB | 25% of MemTotal (29.47 GiB, `/proc/meminfo`), rounded down to a whole GB. Headroom check: MemAvailable 20.4 GiB + current 3 GB > 7 + 4 GB. |
| `work_mem` | 128MB | Largest power of two with `work_mem x hash_mem_multiplier (2) x (max_parallel_workers_per_gather (12) + 1) x peak active backends (3, 60 s sample)` under the bound MemTotal 29.47 - shared_buffers 7 - other containers ~8.2 GiB (redpanda at its 6 GiB limit) - 4 GiB host reserve = 10.3 GiB; 78 x 128MB = 9.75 GiB. Spill evidence: 1,151 GB in 68,243 temp files under the old 8 MB. |
| `shm_size` | 13g | `work_mem 128MB x 2 x 13 x 4` concurrent parallel queries = 13,312 MB, rounded up. A tmpfs cap, not a reservation. Was 512m, which the measured spill (7,392 kB disk in one hash) could overflow. |
| unchanged | — | `maintenance_work_mem` 2GB, `effective_cache_size` 17GB, `max_connections` 200, `max_locks_per_transaction` 16384, `wal_buffers` 8192, `log_min_duration_statement` 1000ms, `max_parallel_workers` 24, `max_parallel_workers_per_gather` 12, `hash_mem_multiplier` 2, `dynamic_shared_memory_type` posix. |

R-12 cause, for the record: the container created 2026-06-22 carried
`work_mem=8MB` on its command line; the compose edit to 64MB (`48bd250fa`,
2026-08-13) never reached the server because the container was only ever
restarted, never recreated, and a restart reuses the recorded `Cmd`. An
unrelated recreation on 2026-10-07 healed `work_mem` to the compose 64MB; the
D-38 apply on 2026-10-11 recreated it again with the values above. Versions
were unchanged across the apply (PostgreSQL 18.4, timescaledb 2.27.1,
vector 0.8.2).

Measured effect on the top read-only spiller (`SELECT DISTINCT ts FROM
market_regimes WHERE regime_group='equity' AND tf='5m' AND
regime_label='low_bull' AND ts <= '2025-12-24 05:15:00+00'`,
`EXPLAIN (ANALYZE, BUFFERS)`, warm runs):

| Metric | Before (work_mem 8MB, buffers 3GB) | After (128MB, 7GB) |
|---|---|---|
| HashAggregate batches | 5 (7,392 kB to disk; temp read 724, written 1,461) | 1, no disk |
| Aggregate memory | 16,441 kB | 32,793 kB |
| Buffers | hit 8,246, read 122,133 | hit 130,379 |
| Execution time | 315.5 ms | 229.4 ms |

Applying a settings change (recreate, do not just restart):

```bash
cd /home/bg/dev/indicagent/production
# gate first: no batch job, no research run, no timer within 30 min (SOP)
docker compose up -d --no-deps --no-build timescaledb
```

`--no-deps` because dependent services must not be bounced, `--no-build`
because the base tag is `latest-pg18` and a rebuild could silently change the
Timescale or pgvector version (record `SELECT version()` and
`SELECT extname, extversion FROM pg_extension` before and after; a change is a
failure). A plain restart is not enough: it reuses the old `Cmd`, which is
exactly how R-12 happened.

Post-change check (a settings edit that did not reach the server is a silent
wrong answer):

```bash
.venv/bin/python -m scripts.ops.db.ops_pg_settings_baseline
# compare section must contain zero entries with status "drift"
docker inspect timescaledb --format '{{index .Config.Labels "com.docker.compose.config-hash"}}'
docker compose -f /home/bg/dev/indicagent/production/docker-compose.yml config --hash timescaledb
# the two hashes must be equal
```

The container's `com.docker.compose.config-hash` label records the compose
content it was created from; `docker compose config --hash` recomputes it from
the file on disk. A mismatch means the file changed without a recreate.

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

One IBKR history stream: `scripts/infrastructure/backfill/ohlcv_history_fetcher.py`
(`indicagent-ibkr-history-fetcher`, phase 189) works the `ohlcv_coverage` queue under its
singleton `FetcherLock`; its update and gap-fill lanes are the gap fill after downtime, so there
is no separate recovery script. Concurrent history streams measured no added throughput (todo
449, 2026-09-27) and contend for the same pacing budget. Alpaca history is
`scripts/ops/bars/ops_bar_nightly.py` with a wide `--days` window. Both write `ohlcv_raw`
last-wins through the ingress contract: a re-fetch replaces a vendor's own stored answer and logs
the old values in `ohlcv_revision`, it never skips an existing row. Commands:
`docs/foundation/instrument-onboarding-sop.md` stage 7 and `docs/reference/cheatsheet.md`.

The v2.x reset, replay and historical-pipeline scripts this section used to list
(`infrastructure_reset_pipeline_data.py`, `infrastructure_run_historical_pipeline.py`,
`debug_lifecycle_replay.py`) were deleted with the v2.x path (plan 185-45).

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
