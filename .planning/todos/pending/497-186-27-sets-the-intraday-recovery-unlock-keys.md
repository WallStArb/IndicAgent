---
status: pending
priority: P1
filed: 2026-10-06
source: 185 session, 185-20 close-out
---

# Phase 186-27 must set the intraday recovery keys and the study verdict gates them

## What

ops_intraday_venue_recovery.py refuses until infra.bar_derivation.intraday_recovery_unlocked is true and
infra.bar_derivation.rebuild_state_table names the rebuild's state table, and venue_bars_intraday (the venue
study's 5m verdict) is true. At rebuild completion 186-27 must set the first two:
{"table": "provenance_batch", "target_tables": ["feature_vectors_v2", "feature_vectors"]}. Venue fallback
is 1d-only (migration 437); 5m recording needs 5m added back to infra.ibkr.venue_fallback.timeframes, which costs
minutes per late name (measured), so do it only when recovery is actually wanted.

## Fix

Add both writes to 186-27's close-out and its verification, with config_history reasons.
