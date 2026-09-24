---
status: closed
priority: P2
filed: 2026-09-24
closed: 2026-09-24
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

## Closure (2026-09-24)

Measured, not assumed: the fail fraction tracks statistical power (cross-asset CIs 3-6x wider than
equity), so any fixed rail reads low power as dislocation. Per-group rails or group exemptions
would only move a threshold on a confounded statistic. Fix (migration 361, feature_lifecycle
stratum_guard): a stratum holds only against its own empirical band once it has guard_min_history
earlier windows; before that it is 'uncalibrated' and never holds. The seeded rails and their APR
keys are deleted. Follow-ups: 414 (power-normalized common-mode statistic), 415 (the lifecycle
needs advancing training windows to act at all).
