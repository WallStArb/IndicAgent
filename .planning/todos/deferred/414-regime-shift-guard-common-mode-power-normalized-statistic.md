---
status: pending
priority: P2
filed: 2026-09-24
source: todo 407 closure (council review of the regime-shift guard)
---

# Replace the guard's fail-fraction with a common-mode, power-normalized change statistic

## Why

The guard asks "is this window a market dislocation, not per-feature decay?". Its input, the
fraction of failing cells per (tf, regime_group), mostly measures statistical power. Measured on
the 176-08 IC, cross-asset slices fail 98.4-100% of cells in a normal window (CIs 3-6x wider than
equity) and equity 94-97%. A binary pass/fail count confounds "signal vanished" with "can't
measure here". Todo 407 removed the level-based hold, so a stratum now holds only against its own
calibrated history (8 earlier windows). That is correct but inert for years, and it still runs on
a power-confounded statistic.

## Design to pre-register before a second training window exists

Per (feature, stratum): z = (IC_now - IC_prev) / sqrt(se_now^2 + se_prev^2), with se from each
cell's bootstrap CI (the size-matched idea used in todo 403). A dislocation is common-mode: the
median z across features in a stratum is strongly negative. Idiosyncratic decay moves single
features while the median stays near 0. Calibrate the hold threshold against a pre-registered
null (feature-label permutation within stratum, or circular shift of the window pair). The
statistic is power-aware by construction, needs no rails or seeded bands, and works from the
second window on. Its code lives in feature_lifecycle, not ic_math: ic_engine must not import it.
When this lands, delete ic_math.evaluate_guard_fraction's rail parameters and the remaining
alpha.decay.guard_* keys it replaces.

## Triage 2026-09-26 (backlog review with the owner)

Deferred (per-feature regime stratification in ic_engine/lifecycle). Gate: reactivate if regime-stratified per-feature IC becomes part of a method in the research methods plan (todo 436). Thin regime x tf cells are the Phase 148 failure shape, so this does not restart by default.
