---
created: 2026-03-04T00:00:00.000Z
title: Add setup performance analytics and aggregator weight feedback
area: intelligence
files:
  - src/intelligence/trading/signal_aggregator.py
  - src/intelligence/trading/cis_weight_updater.py
  - production/scripts/
---

## Problem

Signal outcomes are accumulating in `signal_ledger` (win/loss, pnl_r, 8-class outcome) but no component reads this data to improve signal selection. The aggregator uses static CIS weights; there is no per-setup quality signal. Per Jim Simons principle: "discard unless proven" — setups should earn their weight.

## Solution

**1. Weekly performance report** (scheduled script or service):
```sql
SELECT setup_plugin,
       COUNT(*) as sample_size,
       AVG(CASE WHEN pnl_r > 0 THEN 1.0 ELSE 0.0 END) as win_rate,
       AVG(pnl_r) as avg_r,
       STDDEV(pnl_r) as pnl_stddev
FROM signal_ledger
WHERE resolved_at > NOW() - INTERVAL '30 days'
  AND pnl_r IS NOT NULL
GROUP BY setup_plugin
ORDER BY avg_r DESC;
```

**2. Aggregator weight feedback** — extend `cis_weight_updater.py` (already runs daily) to compute per-setup performance weights and write to a `setup_performance` table. Signal aggregator reads these weights at startup or periodically to bias ranking toward higher-performing setups.

Requires minimum sample size gate (e.g. n ≥ 30 resolved signals) before a setup's weight is adjusted.
