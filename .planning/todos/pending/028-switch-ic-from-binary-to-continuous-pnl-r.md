---
title: "Eliminate binary scoring — use continuous gradients everywhere"
priority: medium
created: 2026-04-08
updated: 2026-04-08
source: Phase 60 UAT — IC metrics all NULL due to zero-variance binary outcomes
status: pending
tags: [ml, ic, signal-metrics, confluence, renaissance, design-principle]
---

## Problem

Binarizing continuous signals discards information. Renaissance principle: *"Never drop data that could contain signal."* Multiple areas suffer from this:

### 1. IC Metric — Binary Win/Loss (Original finding)

`compute_ic()` in `src/intelligence/ml/information_coefficient.py` uses binary outcomes:
```python
binary_outcome = [1.0 if o in WIN_OUTCOMES else -1.0]
```
- **Zero-variance failure** — when no signals hit targets in a window, all outcomes map to -1.0 → Pearson returns None. All 693 IC rows in `signal_metrics_ic` have NULL values.
- **Information loss** — TP1 hit and full target hit both map to `1.0`. A -0.1R loss and -5R loss both map to `-1.0`.

**Fix:** Replace binary `±1.0` with continuous `pnl_r`.

### 2. I6 Confluence Scores — Hard Thresholds → Binary Triggers

Several I6 confluence ideas (see `docs/ideas/i6-confluence-expansion.md`) use hard thresholds that binarize gradients:

- `"If all 3 agree → 1.0"` (flight-to-quality) — should weight by *magnitude* of each component
- `"If spread > 2.0 → 1.0"` (credit stress) — should scale continuously with z-score
- `"If leader in {XLK, XLY} → risk-on"` — should be a continuous rotation score
- `"If |corr deviation| > 2σ → -1.0"` — should scale with deviation magnitude

**Design principle for all new I6 plugins:** Score outputs must be continuous [-1, +1] or [0, 1] gradients, never step functions. Use weighted sums, z-score scaling, or proximity decay — not `if threshold: 1.0 else: 0.0`.

## Scope

### IC Fix (original scope)
- `src/intelligence/ml/information_coefficient.py` — `compute_ic()` signature + implementation
- `src/intelligence/metrics/compute.py` — `compute_ic_metrics()` passes correct data
- `services/signal_metrics_compute_agent.py` — ensure pnl_r is available in rows passed to IC
- `tests/unit/intelligence/test_metrics_compute.py` — update IC tests for continuous outcomes
- Verify `signal_metrics_ic` starts populating non-null IC values after next compute cycle

### Gradient-First Design Principle
- `docs/ideas/i6-confluence-expansion.md` — already updated with gradient-first principle
- All future I6 plugin implementations must follow continuous scoring pattern
- Audit existing `CrossTimeframeConfluencePlugin` for any binary shortcuts

## Notes

- `pnl_r` is already available in signal_ledger rows (zone track) and `market_entry_pnl_r` (market track)
- Need to decide: use zone pnl_r or market pnl_r for IC (or both as separate IC tracks)
- The `is_ic_significant()` gate stays the same (p-value + IC threshold check)
- `IC_MIN_SAMPLE_SIZE=30` stays the same
- The existing I6 plugin is already mostly gradient-based (weighted composites, proximity decay) — it's the *new* ideas that need the guardrail
