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

## Scope check (2026-08-07, while waiting on the 231-instrument OHLCV backfill + CTF Gate 1 refresh)

Verified against live code, not just this todo's own prose (which turns out to have one wrong
example). `FeatureCache` is keyed `f"{symbol}:{tf}"` (`services/feature_vector_pipeline.py:288`)
-- one instance per (symbol, tf), so anything reading `cache._sl_*` state is per-symbol by
construction, not broadcast.

**Confirmed genuinely broadcast** (pure function of `bar_ts`, identical across every symbol in
the pool at that timestamp -- modulo the asset-class-session caveat below):
`dow_sin/cos`, `month_position`, `quarter_position`, `days_to_month_end`, `quarter_cycle_sin/cos`,
`tdom_sin/cos`, `minute_of_hour_sin/cos`, `hour_of_day_sin/cos`, `week_of_month_sin/cos`,
`day_of_month_sin/cos`, `week_of_year_sin/cos`, `in_ny_session`, `in_london_kz`, `in_overlap`,
`power_hour`, `opening_range`, plus the existing `CONTEXT_FEATURES` trio (`vix_z`,
`yield_slope_z`, `flight_quality`).

**Caveat on the session-window flags** (`in_ny_session`/`in_london_kz`/`in_overlap`/`power_hour`):
broadcast only *within* a single asset-class pool sharing one trading-session calendar. Across a
mixed equity/futures/fx cross-sectional pool these could differ by asset class at the same
`bar_ts` -- not verified either way here, needs a direct check before the fix assumes pool-wide
uniformity.

**New candidates not yet in `CONTEXT_FEATURES` or anywhere flagged as broadcast** -- these are
market-level cross-asset ratios computed once, not per-symbol: `tip_tlt_ret_z`, `hyg_lqd_ret_z`,
`sb_corr_fast`, `sb_corr_slow`, `sb_corr_z`. If confirmed broadcast, `CONTEXT_FEATURES`
(`services/ic_engine.py:222`) undercounts the actual broadcast population by at least 5 features
-- worth verifying their compute path before scoping the fix, since any significance-test fix
keyed off `CONTEXT_FEATURES` alone would miss them.

**Confirmed genuinely per-symbol, corrects this todo's own original list** -- `opening_gap_pct`,
`overnight_range_pct`, `gap_filled`, `overnight_high_dist_atr`, `overnight_low_dist_atr`,
`prior_session_high/low/close_dist_atr`, `asian_session_high/low_dist_atr` are all computed from
`cache._sl_session_open` / `cache._sl_prior_session_close` / `cache._sl_overnight_*`
(`src/intelligence/feature_factory.py:5896-5906`) -- per-symbol session state, not shared. This
todo's own "## What" section listed `opening_gap_pct` as a broadcast example; that's wrong, drop
it from the eventual fix's target list.

**Also excluded, correctly** -- the "interaction product" features
(`quarter_momentum_product`, `yield_slope_momentum_product`, `vix_reversion_product`, etc.)
multiply a broadcast term by a per-symbol term (`momentum_z_fast`, `hv_ratio`, ...) -- the product
is per-symbol-varying even though one factor is broadcast, so these do NOT need the broadcast fix.

**Both open verification items resolved (2026-08-07, same session):**

1. **Session-window flags are broadcast pool-wide, no asset-class caveat.** `_in_ny_session`/
   `_in_london_kz`/`_in_overlap`/`_power_hour`/`_opening_range`
   (`src/intelligence/feature_factory.py:1919-1974`) are pure `(bar_ts, config)` functions --
   `config` is one global `FeatureFactoryConfig` with no per-symbol or per-asset-class branch.
   Every symbol in a mixed equity/futures/fx pool gets the identical value at a given `bar_ts`.
   Caveat withdrawn.
2. **`tip_tlt_ret_z`/`hyg_lqd_ret_z`/`sb_corr_fast/slow/z` are confirmed broadcast**, not
   inferred -- the source code says so directly.
   `src/intelligence/feature_cache.py:64-65`: "tip_tlt_ret_z/hyg_lqd_ret_z/sb_corr_* are
   symbol-independent, same update_cross_asset() broadcast mechanism as the 3 [CONTEXT_FEATURES]
   fields above." `update_cross_asset()`'s own docstring (line 582) independently calls them
   "Phase 151 Plan 04's 5 symbol-independent cross-asset additions." All 5 are fed from one
   fixed market-wide ETF bar set (SPY/TLT/SHY/TIP/HYG/LQD), called identically for every
   symbol's cache -- not computed from that symbol's own bars at all.

**Scope check is now complete.** Confirmed broadcast population: 3 `CONTEXT_FEATURES` +
15 calendar/session-timestamp fields + 5 cross-asset fields = **23 broadcast features**, vs.
`CONTEXT_FEATURES`'s current count of 3 -- any fix keyed only off that frozenset undercounts by
20. Remaining scope item is cosmetic, not blocking: cross-check the 23 against
`feature_registry`/`concept_registry` row-by-row to confirm none were missed by a Phase 151+
addition not covered by this class-definition read. The two candidate fixes in "## What needs to
happen" are ready to size against this list -- that design decision is still yours to make.

## References

- `services/ic_engine.py`: `CONTEXT_FEATURES` (the 3 confirmed-broadcast macro features),
  `_compute_one_cross_sectional_cell` (the pooled cross-sectional significance test this gap
  affects)
- [203](../completed/203-canary-rng-seed-not-per-symbol-cross-sectional-pseudo-replication.md) --
  the canary-seed fix that surfaced this gap while verifying per-symbol pseudo-replication was
  fixed for the canary specifically; this todo generalizes the same concern to every broadcast
  feature, not just the canary.
