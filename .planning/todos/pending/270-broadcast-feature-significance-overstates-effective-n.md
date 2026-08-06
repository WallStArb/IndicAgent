---
status: pending
priority: P0
filed: 2026-08-05
source: closing out a stale PRIORITIES.md entry for todo 203 (already closed 2026-08-05, but
  the broadcast-feature significance gap it surfaced was never filed as its own todo)
---

# Broadcast features (symbol-invariant at a given bar_ts) overstate effective N under the
# current pooled cross-sectional significance test

## What

Todo 203 (canary RNG seed fix, closed 2026-08-05) traced a broader, still-open methodology gap
while fixing the canary's per-symbol pseudo-replication issue: `vix_z`, `yield_slope_z`,
`flight_quality`, and every session/calendar feature (`quarter_cycle_sin/cos`, `tdom_sin/cos`,
`minute_of_hour_sin/cos`, `opening_gap_pct`, etc.) are symbol-invariant (broadcast) at a given
`bar_ts` -- the same value is repeated across every symbol in the cross-sectional pool for that
timestamp.

A per-symbol block bootstrap or Fisher-z significance test run on the POOLED cross-sectional
sample treats each (symbol, bar_ts) row as an independent observation. For a broadcast feature,
it is not: `n_symbols` rows at the same `bar_ts` carry only ONE independent draw of information
(the feature's value that instant), not `n_symbols` independent draws. The test therefore
overstates effective N by roughly a factor of `n_symbols` for every broadcast feature, which
understates p-values and overstates apparent significance.

## Why this matters

No significance claim on any broadcast feature (`ic_value`, `ic_sharpe`, `passes_fdr`,
`passes_ci_gate`, etc. in `feature_ic_scores`/`feature_edge_by_regime`) can be trusted at face
value under the current test for as long as this gap stands. This directly touches
CLAUDE.md's "resist overfitting" and "earn promotion through proof (p<0.05, sufficient N)"
principles -- a broadcast feature could clear `passes_fdr` today purely because its true N is
inflated by symbol-count, not because it has real cross-sectional edge.

Scope check, not yet done: which of the current tier-0/tier-1 feature population is actually
broadcast (symbol-invariant) vs genuinely per-symbol-varying needs to be enumerated before
sizing the blast radius -- calendar/session primitives (Phase 151) and the macro/context
features (`vix_z`/`yield_slope_z`/`flight_quality`, `CONTEXT_FEATURES` in `ic_engine.py`) are
confirmed broadcast; most other families (momentum, volatility, structure, SMC) are genuinely
per-symbol and unaffected.

## What needs to happen (design decision, not mine to make unilaterally)

Two candidate fixes, per todo 203's own framing:

1. **Collapse to one row per `bar_ts` before bootstrapping.** For broadcast features only,
   deduplicate the pooled cross-sectional sample down to one observation per `bar_ts` before
   running the significance test -- restores the true independent-observation count. Requires
   detecting which features are broadcast (a per-feature flag, likely on `feature_registry`/
   `concept_registry`) so the test can branch.
2. **A dedicated time-series-only test for broadcast features.** Rather than pooling across
   symbols at all, treat a broadcast feature's significance test as a pure time-series problem
   (one value per `bar_ts`, tested against a matching time-series-only forward return) --
   conceptually cleaner (matches what the feature actually is) but a parallel measurement path
   alongside the existing cross-sectional machinery, more implementation surface.

## References

- `services/ic_engine.py`: `CONTEXT_FEATURES` (the 3 confirmed-broadcast macro features),
  `_compute_one_cross_sectional_cell` (the pooled cross-sectional significance test this gap
  affects)
- [203](../completed/203-canary-rng-seed-not-per-symbol-cross-sectional-pseudo-replication.md) --
  the canary-seed fix that surfaced this gap while verifying per-symbol pseudo-replication was
  fixed for the canary specifically; this todo generalizes the same concern to every broadcast
  feature, not just the canary.
