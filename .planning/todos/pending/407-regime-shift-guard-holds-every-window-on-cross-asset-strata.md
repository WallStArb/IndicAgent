---
status: pending
priority: P2
filed: 2026-09-24
source: first feature_lifecycle replay (todo 402 landing), window 2025-12-24 05:15 UTC
---

# Regime-shift guard holds every window on the cross-asset strata

## What

The first `feature_lifecycle` replay returned `guard_status = hold_high`: eight
(tf, regime_group) strata for the commodity, fx and rates groups (15m/1h/1d) fail at 0.996-1.0,
above the seeded rail `alpha.decay.guard_fail_rate_max = 0.995`, with zero calibration history
(`n_history = 0`, band_source `seeded`). Those groups arrived with the Phase 174 cross-asset
pivot, after the guard's rails were grounded (migration 237, equity-era EIC-04 base rate of
96-98%). A single `hold_high` stratum holds the whole window, and a held window is not lifecycle
evidence, so no feature demotion or promotion can count until each of those strata has
`guard_min_history` (8) windows of history -- possibly never, if their structural fail rate
simply sits above 0.995.

## Fix direction

Decide whether a small cross-asset group's near-total fail rate is dislocation or its normal
state. Candidates: per-group rails in APR, a minimum per-stratum cell count before a stratum is
hold-authoritative that reflects these groups' size, or seeding their history from a null run.
Measure before choosing (distribution of stratum fail fractions per group across the recompute).
