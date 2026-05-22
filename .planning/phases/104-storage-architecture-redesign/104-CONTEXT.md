# Phase 104 Context — Storage Architecture Redesign

## Problem Statement

Disk usage grew from ~70 GB to ~109 GB in one week (39 GB growth). Investigation revealed
this is not junk data — the data is valuable — but the storage design has three structural
violations that cause unnecessary write amplification, redundancy, and inefficiency.

## Audit Findings (May 22, 2026)

### Current table inventory

| Table | Size | Retention | Compression | Growth/week |
|---|---|---|---|---|
| intelligence_features | 19 GB | none | 7d | ~500 MB |
| feature_snapshots_shadow | 13 GB | none | 7d | ~1.5 GB |
| signal_ledger | 12 GB | none | 7d | ~1 GB |
| market_data_ohlcv | 257 MB | none | 30d | stable |
| llm_calls | 101 MB | none | 7d (0 compressed) | ~150 MB |
| signal_lineage | 88 MB | none | 7d (0 compressed) | spiking |

**Seven hypertables have no retention policy — data accumulates forever.**

### Root cause 1: `feature_snapshots_shadow` is a full duplicate

`feature_snapshots_shadow` (13 GB) is a **byte-for-byte copy** of `intelligence_features`.
Same schema, same row counts per day, identical column values confirmed via JOIN. It was
created in Phase 52.5 for parity auditing — comparing the two tables field-by-field to
catch pipeline bugs. The parity auditor (`parity_auditor_agent`) has **never detected a
real violation** since deployment. It is 13 GB of insurance against a bug that doesn't
exist, growing at 1.5 GB/week.

The `feature_snapshot_writer_agent` service consumes from `intelligence.journal` under a
separate consumer group and writes every bar's full feature vector to the shadow table.
This is pure waste.

### Root cause 2: `signal_ledger` schema duplication

`signal_ledger` has 97 columns. The `intelligence_features` table has a column named `i7`
(to be renamed `trading_signals`) which stores a JSONB array of every signal candidate that
fired on that bar. Each element contains all fire-time signal fields: `entry_price`,
`stop_loss`, `targets`, `confidence`, `bucket_scores`, `cis_score`, `supporting_factors`,
`features_snapshot`, `regime_context`, `composite_rank`, `entry_type`, `co_fire_partners`,
`signal_type`, `setup_plugin`, `direction`, and more.

`signal_ledger` duplicates all of these (~60-70 columns) for every signal row. The only
fields `signal_ledger` uniquely owns are lifecycle and outcome data: `activated_at`,
`exit_at`, `exit_price`, `exit_reason`, `outcome`, `pnl_r`, `pnl_dollars`, `mae`, `mfe`,
`bars_in_trade`, the 9 `market_entry_*` columns, `trailing_stop_price`, and shadow outcome
tracking (`shadow_outcome`, `shadow_mae`, `shadow_mfe`).

**Non-winner signals do get outcome tracking** (62% of non-winners have `pnl_r`, `mae`,
`activated_at` written) — this is correct and valuable for training. The problem is the
97-column schema bloat, not the fact of writing non-winners.

### Root cause 3: Signal volume explosion (plugin expansion)

1m signal volume grew 6x in 3 weeks because 9 new plugins were added to the 1m tier:

| Week | 1m Plugins | 1m Signals/Week |
|---|---|---|
| Apr 27 | 18 | 264K |
| May 4 | 18 | 278K |
| May 11 | 25 (+7) | 1.05M (4x jump) |
| May 18 | 27 (+2) | 1.52M |

Each plugin adds ~5-7 non-winner candidate signal rows per bar across all symbols. With
27 plugins, 59 symbols, 390 bars/day → ~1.5M signal_ledger inserts/week. This is by design
(more plugins = more signal candidates = better training data) but the 97-column schema
amplifies the cost.

Non-winner ratio reached 77% this week (1.17M non-winners vs 349K winners in week of
May 18). Non-winners are valuable counterfactual training data — do not stop writing them.

### Root cause 4: Naming convention violation

The `intelligence_features` columns `i1` through `i8` violate the project naming convention
(concept names in snake_case, not tier indices). Correct names:

| Column | Should Be |
|---|---|
| `i1` | `technical_indicators` |
| `i2` | `market_context` |
| `i3` | `pattern_detections` |
| `i4` | `regime_features` |
| `i5` | `confluence_scores` |
| `i6` | `cross_timeframe_context` |
| `i7` | `trading_signals` |
| `i8` | `llm_narrative` |
| `smc` | `smc_features` (acceptable as-is) |

This is a breaking schema migration on a 19 GB compressed hypertable + `feature_snapshots_shadow`
+ all services reading/writing these columns. Do once, together with other migrations.

### Root cause 5: Kafka — 6 topics with no byte retention cap

Topics `intelligence.signal.audit`, `swarm.alpha`, `narratives`, `intelligence.signal_lineage`,
`llm.calls`, `llm.outcomes` have `retention.bytes=-1` (unbounded). They are currently small
(33-41 MB each) because `retention.ms=86400ms` controls them, but have no safety cap.

### Root cause 6: signal_lineage spike

`signal_lineage` had 103K rows on May 19 vs normal ~5K/day — same pattern as the
signal_ledger plugin explosion. Needs investigation to determine if it writes one row per
candidate signal (like signal_ledger) or only per winner. If per-candidate, same redesign
applies.

## Design Principles

Think like a senior quant at Renaissance Technologies:

1. **Single source of truth** — each fact lives in exactly one place. Fire-time signal data
   lives in `intelligence_features.trading_signals` (i7). Lifecycle/outcome data lives in
   `signal_ledger`. Never duplicate.

2. **Separation of concerns** — operational state (live signal tracking, dashboard, alerts)
   vs analytical store (training data, backtesting) are different workloads with different
   schemas, retention, and access patterns. They should not share a table.

3. **Access pattern drives schema** — OLTP needs fast point updates (lifecycle writes);
   ML training needs columnar bulk reads (no JSONB unnesting). These are incompatible in
   one table.

4. **Automation over manual** — retention policies, compression, and materialization jobs
   should run automatically via TimescaleDB scheduler and systemd timers. No manual cleanup.

5. **Every stored byte must earn its keep** — if the data can be derived from a JOIN, don't
   store it twice.

## Target Architecture

Three stores, each with one job:

```
intelligence_features          signal_ledger (slimmed)       ml_signal_training (new)
─────────────────────          ───────────────────────       ──────────────────────────
Canonical feature vector       Lifecycle/outcome only        Materialized training set
All tiers i1-i8 (renamed)      ~25 columns                   Flat, columnar, pre-joined
ALL signal candidates          signal_id FK to i7            Nightly rebuild automation
in trading_signals (i7)        Fast UPDATEs                  Typed columns, no JSONB
Compressed after 7d            Winners + losers retained     Designed for ML reads
2yr retention                  1yr retention                 1yr rolling, 7d compression
```

### signal_ledger slim schema (~25 columns)

Keep only what `trading_signals` (i7) does NOT have:

```
signal_id, ts, symbol, tf, is_shadow, was_selected, status, is_backfill,
signal_schema_version,
activated_at, activation_price, exit_at, exit_price, exit_reason,
outcome, pnl_ticks, pnl_r, pnl_dollars, mae, mfe, bars_in_trade,
market_entry_at, market_entry_exit_at, market_entry_outcome,
market_entry_pnl_r, market_entry_mae, market_entry_mfe, market_entry_bars_in_trade,
market_entry_gap_bars, market_entry_price, market_entry_exit_price,
trailing_stop_price, staleness_score, staleness_trigger_reason,
shadow_tracking_start_ts, shadow_outcome, shadow_mae, shadow_mfe
```

Training JOIN: `signal_ledger (outcome, pnl_r, ...)` JOIN
`intelligence_features.trading_signals` (unnested, `entry_price`, `confidence`, ...) via `signal_id`.

### Parity auditor replacement

Replace `feature_snapshots_shadow` + `parity_auditor_agent` full field-by-field comparison
with a lightweight SQL health check:

```sql
-- Fires an alert if any (symbol, tf) bar is missing from intelligence_features
-- within the last 10 minutes. Replaces the entire shadow table.
SELECT symbol, tf, count(*) AS feature_rows
FROM intelligence_features
WHERE ts > NOW() - INTERVAL '10 minutes'
GROUP BY symbol, tf
HAVING count(*) < expected_bars_in_window(symbol, tf);
```

### ml_signal_training (new, nightly automated)

Nightly systemd timer job:
1. Unnests `intelligence_features.trading_signals` (i7) for the previous trading day
2. Left-joins `signal_ledger` on `signal_id` for resolved outcomes
3. Flattens all JSONB tier values into typed columns
4. Appends to `ml_signal_training` hypertable
5. Backfill job: as outcomes resolve, update `ml_signal_training` rows

Result: ML training reads flat typed rows — no JSONB, no joins, no unnesting.

## Estimated Impact

| Change | Disk Reclaimed | Growth Rate Reduction |
|---|---|---|
| Drop `feature_snapshots_shadow` | 13 GB immediately | -1.5 GB/week |
| Slim `signal_ledger` (stop writing dupe cols) | ~6 GB over time | ~4x smaller rows |
| Retention policies on all tables | Bounded growth | Automated |
| Kafka byte caps | Safety net | Automated |
| `ml_signal_training` (new) | +1 GB/week | Replaces ad-hoc JSONB queries |

Total disk growth drops from ~6 GB/week to ~1.5 GB/week.
Memory pressure (17 GB used, 11 GB swap) is partially driven by TimescaleDB holding
uncompressed hot chunks — slimmer rows reduce buffer pool pressure.

## Task Breakdown (captured as session todos)

1. Rename `intelligence_features` tier columns to concept names (i1→i8, breaking migration)
2. Document full storage inventory in `docs/plans/storage-audit.md`
3. Add retention policies to all 7 hypertables missing them
4. Set `retention.bytes=500MB` on 6 unbounded Kafka topics
5. Remove `feature_snapshots_shadow` + replace parity auditor with SQL health check
6. Design slim `signal_ledger` schema (produce `docs/plans/signal-ledger-redesign.md`)
7. Implement `signal_ledger` migration + update all write paths
8. Design and implement `ml_signal_training` materialized store + nightly automation
9. Investigate `signal_lineage` spike — audit write amplification pattern

## Dependencies and Order

```
2 (audit doc) → feeds everything
3 + 4 (retention/kafka) → parallel, immediate, no schema changes
5 (drop shadow) → after 3 drains existing data (or truncate with backup)
6 (design slim ledger) → parallel with 5
9 (lineage audit) → parallel with 5+6
7 (implement ledger) → after 6 + 1 (do rename and slim together)
8 (ml training store) → after 7
```

Tasks 3 and 4 are safe to execute immediately — pure configuration, no code changes.
Tasks 1, 5, 7, 8 are breaking changes requiring service updates and migrations.

## Key Constraints

- `intelligence_features` is a 19 GB compressed hypertable — column renames require
  `ALTER TABLE` on compressed chunks, which TimescaleDB handles but requires decompression
  of active chunks first. Plan for a maintenance window or rolling approach.
- `signal_ledger` is written by `signal_writer_agent` and read by `signal_tracker_compute`,
  `lifecycle_writer_agent`, `signal_auditor_agent`, `signal_metrics_compute`, `graduation_compute`,
  `ml_training_agent`, and the dashboard API. All read paths must be updated.
- Non-winner signals must continue being written to `signal_ledger` — they receive outcome
  tracking (62% have resolved pnl_r/mae). Only the fire-time duplicate columns are removed.
- `feature_parity_violations` table (currently 40 KB, empty) can be dropped with the
  shadow table.
