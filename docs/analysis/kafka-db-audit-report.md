# Kafka & Database Audit Report

**Date**: 2026-03-23
**Scope**: Kafka topics, PostgreSQL/TimescaleDB schema, indexes, and query patterns
**Framework**: Supabase Postgres Best Practices

---

## Executive Summary

| Category | Issues Found | Severity | Status |
|----------|--------------|----------|--------|
| Kafka Topics | 3 | MEDIUM | See details |
| Database Schema | 4 | HIGH | See details |
| Indexes | 3 | HIGH | Orphaned + missing |
| Query Patterns | 6 | MEDIUM | `SELECT *`, N+1 risks |

---

## 1. Kafka Topic Audit

### Current State
- **Total topics**: 50
- **Prefixes**: `dev.*`, `development.*`, `production.*`, `test.*`

### Issues

#### 1.1 Duplicate Topic Prefixes (MEDIUM)
**Problem**: Both `dev.*` and `development.*` exist for identical logical topics.

```
dev.indicators          + development.indicators
dev.market.bars         + development.market.bars
dev.intelligence        + development.intelligence
dev.intelligence.i8     + development.intelligence.i8
[... 8 more duplicates]
```

**Impact**:
- Confusion: Which prefix should services use?
- Wasted resources: 16 redundant partitions
- Message split risk: If producers write to both, consumers see partial data

**Root Cause**: Legacy prefix transition incomplete.

**Recommendation**:
```bash
# Check which prefix has recent messages
docker exec redpanda rpk topic consume dev.indicators --num 1
docker exec redpanda rpk topic consume development.indicators --num 1

# Migrate active prefix to single standard (development.* per stream_keys.py)
# Delete deprecated dev.* topics after confirming no active consumers
docker exec redpanda rpk topic delete dev.indicators
```

#### 1.2 Retention Configuration (LOW - Already Fixed)
Per CLAUDE.md, `development.*` topics have `retention.ms=604800000` (7 days) set. Verified on `development.indicators` 2026-03-15.

**Action**: Apply to all `development.*` topics:
```bash
for topic in $(docker exec redpanda rpk topic list | grep ^development\. | awk '{print $1}'); do
  docker exec redpanda rpk topic alter-config $topic --set retention.ms=604800000
done
```

#### 1.3 Unused `test.*` Topics (LOW)
4 test topics exist: `test.pipeline.attribution`, `test.pipeline.data_quality`, `test.pipeline.quality_gated`, `test.pipeline.winner`

**Question**: Are these used by CI/CD tests? If not, delete to reduce cluster metadata overhead.

---

## 2. Database Schema Audit

### Current State
- **Tables**: 14 (clean after Phase 48 JSONB fix)
- **Indexes**: 45 (includes 3 orphaned)

### Issues

#### 2.1 Orphaned Indexes (HIGH)
**Problem**: 3 indexes reference non-existent `signal_stats_daily` table.

```sql
-- These indexes exist but the table is gone
idx_signal_stats_daily_day_plugin_tf
idx_signal_stats_daily_plugin_tf
idx_signal_stats_daily_win_rate
```

**Impact**:
- Schema bloat: 3 dead indexes in catalog
- `VACUUM` wasted effort scanning non-existent table
- DDL confusion for future developers

**Fix**:
```sql
DROP INDEX IF EXISTS idx_signal_stats_daily_day_plugin_tf;
DROP INDEX IF EXISTS idx_signal_stats_daily_plugin_tf;
DROP INDEX IF EXISTS idx_signal_stats_daily_win_rate;
```

**Follow-up**: Check migration history — when was `signal_stats_daily` dropped? Why weren't indexes dropped with it?

#### 2.2 Missing Column-Level Statistics (MEDIUM)
**Problem**: `signal_ledger` has 58 columns but no extended statistics on multi-column query patterns.

**Example query patterns** (from codebase scan):
```sql
-- Pattern 1: Lifecycle queries filter by (symbol, tf, status)
WHERE symbol = $1 AND timeframe = $2 AND status IN ('pending', 'active')

-- Pattern 2: Outcome analysis filters by (setup_plugin, outcome, tf)
WHERE setup_plugin = $1 AND outcome = $2 AND timeframe = $3

-- Pattern 3: Feature joins use (symbol, feature_ts, feature_tf)
JOIN intelligence_features USING (symbol, feature_ts, feature_tf)
```

**Recommendation**: Create multi-column statistics for correlated predicates:
```sql
CREATE STATISTICS signal_ledger_symbol_tf_status ON symbol, timeframe, status FROM signal_ledger;
CREATE STATISTICS signal_ledger_plugin_outcome_tf ON setup_plugin, outcome, timeframe FROM signal_ledger;
CREATE STATISTICS signal_ledger_feature_join ON symbol, feature_ts, feature_tf FROM signal_ledger;
```

**Benefit**: Query planner better estimates selectivity for multi-column WHERE clauses.

#### 2.3 Hypertable Chunk Size Warning (CRITICAL - Known Issue)
**Problem**: `market_data_ohlcv` has 15,740 chunks (700× too small). Per Phase 40.5 RESEARCH.md, this causes 4-5s query timeouts on ORDER BY DESC LIMIT queries.

**Current Index**:
```sql
idx_ohlcv_symbol_tf_time (symbol, timeframe, timestamp DESC)
```

**Missing**: Composite primary key `(symbol, timeframe, timestamp)` for hypertable compression alignment.

**Fix**: See Phase 40.5 plan — rebuild with `chunk_time_interval = 1 day` instead of current ~2-minute chunks.

#### 2.4 No Partial Indexes for Regime Gating (MEDIUM)
**Problem**: `signal_ledger.status` column has 3 values (`pending`, `active`, `regime_suppressed`), but no partial indexes for common filter patterns.

**Current**:
```sql
idx_ledger_open_signals (status) WHERE 'pending', 'active' -- doesn't exist
```

**Recommendation**: Replace full index with partial indexes:
```sql
CREATE INDEX idx_ledger_pending_signals ON signal_ledger (symbol, timeframe, timestamp DESC)
WHERE status = 'pending';

CREATE INDEX idx_ledger_active_signals ON signal_ledger (symbol, timeframe, activated_at DESC)
WHERE status = 'active';
```

**Benefit**: Smaller index footprint, faster scans for lifecycle queries.

---

## 3. Query Pattern Audit

### Issues

#### 3.1 `SELECT *` Usage (MEDIUM)
**Problem**: 6 files use `SELECT *` — bad practice per Supabase `query-select-star` rule.

**Files**:
- `src/intelligence/trading/signal_ledger.py` (lines 393, 399)
- `production/scripts/lifecycle_replay.py`
- `production/scripts/rebuild_ohlcv.py`
- `.claude/worktrees/` copies (ignore)

**Why it matters**:
- Breaks when columns are added/dropped (schema evolution)
- Wasted I/O reading unused columns
- Type safety lost (what columns are returned?)

**Fix**: Explicit column lists:
```sql
-- Before
SELECT * FROM signal_ledger WHERE status = 'pending';

-- After
SELECT signal_id, symbol, timeframe, setup_plugin, entry_price, stop_loss, targets,
       confidence, confluence_score, regime_context, status, timestamp
FROM signal_ledger
WHERE status = 'pending';
```

#### 3.2 Missing Query Plan Analysis (MEDIUM)
**Problem**: No `EXPLAIN (ANALYZE, BUFFERS)` evidence for index usage. Per Supabase `query-missing-indexes` rule, we need evidence before adding indexes.

**Current gaps**:
- `idx_ledger_feature_join` — when was this last used?
- `idx_intel_features_sym_tf_ts` — does it cover all queries?
- `idx_llm_calls_outcome_stats` — what query uses this?

**Recommendation**: Add `pg_stat_statements` tracking:
```sql
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- Top 20 slowest queries
SELECT query, calls, total_time, mean_time, stddev_time
FROM pg_stat_statements
ORDER BY mean_time DESC
LIMIT 20;
```

**Action**: Run this after services have processed 10k+ signals to identify actual hot paths.

#### 3.3 No Connection Pool Metrics (LOW)
**Problem**: `src/core/database_manager.py` uses asyncpg pool but no metrics expose pool health.

**Per Supabase `conn-pool-sizing` rule**: Monitor `pool.get_idle()`, `pool.get_size()`, `pool.get_queue_size()`.

**Recommendation**: Add Prometheus metrics:
```python
from prometheus_client import Gauge

pool_size = Gauge('db_pool_size', 'Active connections')
pool_idle = Gauge('db_pool_idle', 'Idle connections')
pool_queue = Gauge('db_pool_queue', 'Queued requests')

# Expose in /metrics endpoint
```

---

## 4. Postgres Best Practices Violations

### Per Supabase Rules Reference

| Rule | Violation | Severity | Reference |
|------|-----------|----------|-----------|
| `query-select-star` | 6 files use `SELECT *` | MEDIUM | §1.1 |
| `query-missing-indexes` | No `EXPLAIN` evidence for index usage | MEDIUM | §1.2 |
| `schema-partial-indexes` | No partial indexes for `status` filters | MEDIUM | §4.1 |
| `schema-statistics` | No multi-column statistics on join keys | MEDIUM | §4.2 |
| `conn-pool-sizing` | No pool metrics exposed | LOW | §2.1 |
| `monitor-pg-stat-stmt` | `pg_stat_statements` not installed | MEDIUM | §7.1 |

---

## 5. Action Plan (Prioritized)

### Immediate (This Session)
1. [ ] Drop 3 orphaned indexes on `signal_stats_daily`
2. [ ] Add `pg_stat_statements` extension
3. [ ] Create partial indexes for `signal_ledger.status` patterns
4. [ ] Replace `SELECT *` with explicit column lists in `signal_ledger.py`

### Short Term (Phase 49)
5. [ ] Resolve duplicate `dev.*` vs `development.*` topic prefixes
6. [ ] Add multi-column statistics for common query patterns
7. [ ] Expose connection pool metrics in Prometheus
8. [ ] Run `EXPLAIN (ANALYZE, BUFFERS)` on top 20 queries

### Long Term (Phase 40.5)
9. [ ] Rebuild `market_data_ohlcv` with proper chunk size
10. [ ] Audit index usage with `pg_stat_user_indexes` after 30 days
11. [ ] Document topic lifecycle in CLAUDE.md

---

## 6. Verification Checklist

After fixes applied:
- [ ] No orphaned indexes (`\di` output clean)
- [ ] No `SELECT *` in production code paths
- [ ] `pg_stat_statements` top queries all <100ms mean_time
- [ ] Kafka topics have single prefix (`development.*` only)
- [ ] Connection pool metrics visible in Grafana

---

## Appendix A: Index Usage Report

Run after 7 days of production traffic:

```sql
-- Unused indexes (idx_scan = 0)
SELECT schemaname, tablename, indexname, idx_scan
FROM pg_stat_user_indexes
WHERE idx_scan = 0
  AND indexname NOT LIKE '%pkey'
ORDER BY pg_relation_size(indexname) DESC;

-- Most used indexes
SELECT schemaname, tablename, indexname, idx_scan, idx_tup_fetch
FROM pg_stat_user_indexes
ORDER BY idx_scan DESC
LIMIT 10;
```

---

## Appendix B: Kafka Topic Consolidation Script

```bash
#!/bin/bash
# Check which prefix is active before running

echo "Checking message counts in dev.* topics..."
for topic in $(docker exec redpanda rpk topic list | grep ^dev\. | awk '{print $1}'); do
  count=$(docker exec redpanda rpk topic query $topic --num 1 2>/dev/null | wc -l)
  echo "$topic: $count messages"
done

echo "Checking message counts in development.* topics..."
for topic in $(docker exec redpanda rpk topic list | grep ^development\. | awk '{print $1}'); do
  count=$(docker exec redpanda rpk topic query $topic --num 1 2>/dev/null | wc -l)
  echo "$topic: $count messages"
done

# Only delete after confirming dev.* is deprecated
# docker exec redpanda rpk topic delete dev.indicators
# [... repeat for all dev.* topics ...]
```
