---
title: "Switch IC from binary win/loss to continuous pnl_r gradient"
priority: medium
created: 2026-04-08
source: Phase 60 UAT — IC metrics all NULL due to zero-variance binary outcomes
status: pending
tags: [ml, ic, signal-metrics, renaissance]
---

## Problem

`compute_ic()` in `src/intelligence/ml/information_coefficient.py` uses **binary** outcomes:
```python
binary_outcome = [1.0 if o in WIN_OUTCOMES else -1.0]
```

This causes two issues:
1. **Zero-variance failure** — when no signals hit targets in a window, all outcomes map to -1.0 → Pearson returns None. Currently all 693 IC rows in `signal_metrics_ic` have NULL values.
2. **Information loss** — TP1 hit, TP1+2 hit, and full target hit all map to same `1.0`. A -0.1R loss and a -5R loss both map to same `-1.0`. The gradient is discarded.

## Fix

Replace binary `±1.0` with continuous `pnl_r` as the IC outcome variable:
```python
# Before: binary
ic_score = pearsonr(confidence, [1.0 if win else -1.0])
# After: continuous
ic_score = pearsonr(confidence, pnl_r)
```

This matches Renaissance principles: "Never drop data that could contain signal." The continuous pnl_r preserves magnitude information that binary discards.

## Scope

- `src/intelligence/ml/information_coefficient.py` — `compute_ic()` signature + implementation
- `src/intelligence/metrics/compute.py` — `compute_ic_metrics()` passes correct data
- `services/signal_metrics_compute_agent.py` — ensure pnl_r is available in rows passed to IC
- `tests/unit/intelligence/test_metrics_compute.py` — update IC tests for continuous outcomes
- Verify `signal_metrics_ic` starts populating non-null IC values after next compute cycle

## Notes

- `pnl_r` is already available in signal_ledger rows (zone track) and `market_entry_pnl_r` (market track)
- Need to decide: use zone pnl_r or market pnl_r for IC (or both as separate IC tracks)
- The `is_ic_significant()` gate stays the same (p-value + IC threshold check)
- `IC_MIN_SAMPLE_SIZE=30` stays the same
