# Storage Architecture Audit

**Date:** 2026-05-22 | **Phase:** 104

## Current Inventory

| Table | Size | Chunks | Compression | Retention | Growth/week |
|---|---|---|---|---|---|
| intelligence_features | 19 GB | 77 | 7d | **NONE** | ~500 MB |
| signal_ledger | 12 GB | 77 | 7d (recompress daily) | **NONE** | ~1 GB |
| feature_snapshots_shadow | 13 GB | 14 | 7d | **NONE** | ~1.5 GB |
| market_data_ohlcv | 257 MB | 104 | 30d | **NONE** | stable |
| llm_calls | 101 MB | 1 | 7d | **NONE** | ~150 MB |
| signal_lineage | 88 MB | 2 | 7d | **NONE** | spiking |
| signal_transform_log | — | 0 | 7d | **NONE** | minimal |
| macro_features | — | 18 | 7d | **NONE** | minimal |
| ctx_events | — | 0 | 7d | **NONE** | minimal |
| alpha_multiplier_shadow | — | 0 | 7d | **NONE** | minimal |
| signal_metrics_dq_failures | — | 0 | 7d | 90d (job 1031) | minimal |
| service_health_events | — | 2 | 2d | 7d (job 1033) | minimal |
| dlq_events | — | 0 | — | 30d (job 1034) | minimal |
| intelligence_metrics | — | 0 | — | 1yr (job 1025) | minimal |
| drift_monitor | — | 0 | 30d | **NONE** | minimal |

**9 hypertables have no retention policy** — data accumulates forever.

## Root Causes

1. **feature_snapshots_shadow duplication** — 13 GB byte-for-byte copy of intelligence_features. Parity auditor has never detected a real violation.

2. **signal_ledger 97-column bloat** — ~47 fire-time columns are duplicated from intelligence_features.i7 JSONB. Slim to ~38 lifecycle-only columns.

3. **Signal volume explosion** — 1m signal volume grew 6x in 3 weeks (27 plugins, 59 symbols → 1.52M signals/week). By design, but 97-column schema amplifies cost.

4. **Naming convention violation** — i1..i8 columns should be concept names (technical_indicators, market_context, etc.).

5. **6 unbounded Kafka topics** — intelligence.signal.audit, swarm.alpha, narratives, intelligence.signal_lineage, llm.calls, llm.outcomes have retention.bytes=-1.

6. **signal_lineage spike** — Confirmed per-winner only (5 rows/signal = 5 agents). Not write amplification; proportional to winner count.

## Target Architecture

Three stores, each with one job:

```
intelligence_features          signal_ledger (slimmed)       ml_signal_training (new)
─────────────────────          ───────────────────────       ──────────────────────────
Canonical feature vector       Lifecycle/outcome only        Materialized training set
Renamed columns (see below)    ~38 columns                   Flat typed columns, no JSONB
ALL signal candidates          signal_id FK to i7            Nightly rebuild
in trading_signals (i7)        Fast UPDATEs                  Designed for ML reads
Compressed 7d, 2yr retention   Compressed 7d, 1yr retention  Compressed 7d, 1yr retention
```

### Column rename mapping

| Old | New |
|---|---|
| i1 | technical_indicators |
| i2 | market_context |
| i3 | pattern_detections |
| i4 | regime_features |
| i5 | confluence_scores |
| i6 | cross_timeframe_context |
| i7 | trading_signals |
| i8 | llm_narrative |
| smc | smc (unchanged) |

## Migration Sequence

1. Install retention policies on 9 hypertables (Plan 01)
2. Apply 500 MB Kafka byte caps on 6 topics (Plan 01)
3. Drop feature_snapshots_shadow + retire parity auditor (Plan 02)
4. Rename i1..i8 + slim signal_ledger in one maintenance window (Plan 03)
5. Create ml_signal_training hypertable + nightly timer (Plan 04)

## Estimated Impact

| Change | Disk Reclaimed | Growth Reduction |
|---|---|---|
| Drop feature_snapshots_shadow | 13 GB immediately | -1.5 GB/week |
| Slim signal_ledger | ~6 GB over time | ~4x smaller rows |
| Retention policies | Bounded growth | Automated |
| Kafka byte caps | Safety net | Automated |
| ml_signal_training (new) | +1 GB/week | Replaces ad-hoc JSONB queries |

**Total: disk growth drops from ~6 GB/week to ~1.5 GB/week.**

## Reference

Migration SQL: `db/migrations/090_retention_policies.sql`
