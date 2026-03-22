---
created: 2026-03-22T12:24:29.800Z
title: Retry roll detection validation when market_data_5m populates
area: general
files:
  - production/scripts/validate_roll_detection.py
  - production/migrations/049_roll_premium_pct.sql
  - services/tws_daemon.py
---

## Problem

During Phase 47-02, the offline roll detection validation script (D-21 pre-enable gate) returned **SKIP (exit code 2)** — the `market_data_5m` view is empty after DB cleanup. `ROLL_MONITOR_ENABLED` was left as `false` because the algorithm could not be validated without historical data.

The algorithm itself is correct (calendar-driven + z-score, bug D-16 fixed). This todo captures the remaining graduation steps once data is available.

## Solution

1. Wait for IBKR to be live and `market_data_5m` to accumulate 5m bars
2. Run validation:
   ```bash
   .venv/bin/python production/scripts/validate_roll_detection.py
   ```
   Must exit code 0 (PASS) — if SKIP or FAIL, investigate before enabling.
3. Apply DB migration:
   ```bash
   docker cp production/migrations/049_roll_premium_pct.sql timescaledb:/tmp/049_roll_premium_pct.sql
   docker exec timescaledb psql -U postgres -d indicagent -f /tmp/049_roll_premium_pct.sql
   ```
4. Add to `.env`:
   ```
   ROLL_MONITOR_ENABLED=true
   ```
5. Restart services:
   ```bash
   echo '***REDACTED-SUDO-PASSWORD***' | /usr/bin/sudo.ws -S systemctl restart indicagent-tws indicagent-feature-pipeline indicagent-signal-generator indicagent-signal-lifecycle indicagent-feature-writer
   ```
6. Soak 5 clean trading days — monitor `:9125` (feature-pipeline) and `:9112` (signal-generator) for error rates
7. After soak: remove all `roll_monitor_enabled` / `ROLL_MONITOR_ENABLED` feature-flag scaffolding from services per 47-03 Task 2
