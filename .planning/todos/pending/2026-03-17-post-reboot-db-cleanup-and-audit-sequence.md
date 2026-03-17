---
created: 2026-03-17T22:40:26.334Z
title: Post-reboot DB cleanup and audit sequence
area: database
files:
  - production/migrations/
  - docs/plans/2026-03-17-automated-roll-detection-design.md
---

## Problem

After shipping phases 31-34 in one session, services need a clean restart and DB needs housekeeping before Phase 38 execution.

Key findings from health audit (2026-03-17):
- `market_data_ohlcv` has **15,740 chunks** due to space partitioning — causing query timeouts at scale. Rebuild todo exists: `2026-03-15-rebuild-market-data-ohlcv-without-space-partitioning.md`
- `signal_ledger` is **6GB**, lifecycle UPDATEs averaging 34ms — index audit needed
- `signal_ledger` SELECT on status/symbol at 28ms × 39k calls — likely missing composite index
- Services running stale code from pre-phase-31 deployments

## Solution

Work through in this order after reboot:

### 1. Restart all services (post-reboot)
```bash
sudo systemctl restart indicagent-tws indicagent-indicator indicagent-market-analysis indicagent-signal-generator indicagent-signal-lifecycle indicagent-ai-narrative indicagent-feature-writer indicagent-llm-writer indicagent-api
```

### 2. Rebuild market_data_ohlcv without space partitioning
See todo: `2026-03-15-rebuild-market-data-ohlcv-without-space-partitioning.md`
15,740 chunks → target ~380 (time-only partitioning like other hypertables).
Do this before Phase 38 — disruptive window needed.

### 3. Signal ledger index audit
```sql
-- Check UPDATE path indexes
EXPLAIN (ANALYZE, BUFFERS) UPDATE signal_ledger SET status = 'active' WHERE signal_id = '...' AND symbol = 'ES';
-- Check SELECT path
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM signal_ledger WHERE status IN ('pending','active','regime_suppressed') AND symbol = 'ES' AND exit_at IS NULL;
```
Add composite index if missing: `(symbol, status, exit_at)` on signal_ledger.

### 4. VACUUM + reset pg_stat_statements
```sql
-- In standalone psql (not transaction block)
VACUUM ANALYZE signal_ledger;
VACUUM ANALYZE intelligence_features;
SELECT pg_stat_statements_reset();
```

### 5. Proceed to Phase 38
Clean infra before roll detection lands.
