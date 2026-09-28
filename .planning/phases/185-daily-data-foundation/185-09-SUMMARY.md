---
phase: 185-daily-data-foundation
plan: 09
subsystem: ibkr-history-stream
tags: [resource-lease, advisory-lock, d1-capture, nightly-backfill, d-29]

# Dependency graph
requires: [185-02]
provides:
  - src/core/resource_lease.py: ResourceLease, a session-level PostgreSQL advisory-lock lease (Ring 0); bulk tier yields to any waiter, priority tier only to none; holders are named in pg_stat_activity as `lease:<name>:<tier>:<holder>`
  - scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py: takes the `ibkr_history_stream` lease, releases it at (symbol, tf) unit boundaries, and records every request and 1d answer in D1 through OhlcvObservationWriter
  - scripts/ops/bars/_campaign.py: campaign preflight
  - scripts/infrastructure/backfill/infrastructure_nightly_backfill.py: runs at priority tier and waits for the lease instead of skipping
  - tests/unit/test_ibkr_history_lease_boundary.py: CI check that every `fetch_historical_bars` caller holds the lease or is allow-listed with a reason
affects: [185-12, 185-13, 185-15]

key-files:
  created:
    - src/core/resource_lease.py
    - tests/unit/core/test_resource_lease.py
    - tests/unit/scripts/test_historical_pipeline_d1_capture.py
    - tests/unit/scripts/test_bar_campaign_preflight.py
    - tests/unit/scripts/test_nightly_lease.py
    - tests/unit/test_ibkr_history_lease_boundary.py
  modified:
    - scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py
    - scripts/infrastructure/backfill/infrastructure_nightly_backfill.py
    - scripts/ops/bars/_campaign.py
    - services/ohlcv_observation_writer.py
    - tests/unit/scripts/test_infrastructure_nightly_backfill.py
    - docs/operations/operations-database.md

key-decisions:
  - "The lease is a session advisory lock, so a crashed holder cannot leave it stale: the server releases it when the session ends"
  - "The nightly no longer skips while the todo 449 chain runs; a long backfill can no longer cost the daily bars a night"

requirements-completed: [D-05, D-16, D-20, D-29, D-30]

completed: 2026-09-28
---

# Plan 185-09: history-stream lease, D1 capture, nightly waiting summary

**One IBKR history stream is now shared by rule: the todo 449 chain holds the lease at bulk tier and yields at unit boundaries, the nightly waits at priority tier instead of skipping, and the backfill records every request and 1d answer in D1**

## Task commits
1. **Task 1 RED: ResourceLease tests** - `7c1d889a4`
2. **Task 1 GREEN: ResourceLease** - `1cf95037b`
3. **Task 2 RED: pipeline D1 capture, lease checkpoints, campaign preflight, CI boundary tests** - `e70dcf1c5`
4. **Task 2 GREEN: pipeline takes the lease and captures D1** - `955870623`
5. **Task 3 RED: nightly lease waiting tests** - `41174c3ab`
6. **Task 3 GREEN: nightly waits on the lease** - `e79544d79`
7. **Task 4: chain cut-over doc callout, STATE and ROADMAP** - this commit

## Task 4 cut-over
The chain's pipeline process (pid 1883343, client 46) restarted onto the lease code at 2026-09-28 08:10 EDT, after the task 3 commit (07:40 EDT), through the lane loop's normal next attempt (attempt 8). It holds `lease:ibkr_history_stream:bulk:historical-pipeline:46` in `pg_stat_activity`, and the lane log shows `historical_pipeline.d1_captured` lines with BWIN completed and BWX in progress at 08:55 EDT. The 185-09 executor died on a provider rate-limit error (HTTP 429) after these commits, so this session verified the cut-over state instead of repeating the kill procedure: no kill was needed and no orphan sweep applied. The one leftover step, the operations doc callout, is now written.

## Deferred
Three lease-free `fetch_historical_bars` callers are allow-listed in the CI boundary test and logged in `deferred-items.md`: `services/backfill_feature_factory.py`, the chunk and rate-limit probe script, and `services/dividend_event_writer.py` (the last self-expires when 185-15 lands).

## Verification
- tests for tasks 1 to 3 green (resource lease, D1 capture, campaign preflight, lease boundary, nightly lease, nightly backfill)
- lease session present in `pg_stat_activity`; lane progressing after the cut-over
