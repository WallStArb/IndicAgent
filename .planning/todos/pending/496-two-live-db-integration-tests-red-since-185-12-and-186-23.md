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

## Parity replay retired (2026-11-04, migration 575)

`tests/integration/test_ic_parity_replay.py` is deleted: it replayed POOLED cross-sectional cells
of the ic_engine-era `feature_ic_scores`, which migration 575 dropped (after `forward_returns` in
186-23), so nothing it reads exists. Its committed 186-20 parity report stays as the evidence. The
pure harness (`tests/unit/measure/parity_replay.py`) and its unit tests remain. Left here: the
quarantine check.

