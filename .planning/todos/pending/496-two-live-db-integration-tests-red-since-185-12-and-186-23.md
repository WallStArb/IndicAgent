---
status: pending
priority: P2
filed: 2026-10-06
source: 185 session, 185-18 integration run
---

# Two live-database integration tests are red for unrelated reasons

## What

tests/integration/test_ic_parity_replay.py reads the forward_returns table dropped by 186-23, and
tests/integration/test_bar_quality_flag_quarantine.py compares migration 381's one-time legacy copy
(567 flags) with market_data_ohlcv rows that 185-12 moved (35 left). Both read the live database, so the
integration suite is never fully green.

## Fix

Decide per test with its owner: retire the parity replay (its premise is gone) and rewrite the quarantine
check against the live invariant (every quarantined bar is absent from the tradeable view), not the copy count.
