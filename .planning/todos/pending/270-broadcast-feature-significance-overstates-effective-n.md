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
addition not covered by this class-definition read.

## Design decision (2026-08-11) -- resolves the "not mine to make unilaterally" note above

Both candidate fixes converge on the same underlying statistical answer (a time-series-only
correlation for broadcast features), so the real choice is architectural: one shared test
primitive with a data-driven branch (fix 1's framing), vs. two parallel measurement systems
(fix 2). Rejecting fix 2 outright -- this codebase already paid for a parallel-system mistake
once (`feature_registry`/`concept_registry`, retired Phase 170, migration 311) and the DAG
principle against duplicate systems exists precisely to prevent a repeat. Decision: **one
significance-test primitive (`_subsample_and_rank`), branch only at sample construction.**

**New finding while grounding this against live code (supersedes the "not yet scoped" status):**

1. The 3 `CONTEXT_FEATURES` (`vix_z`/`yield_slope_z`/`flight_quality`) do NOT go through the
   pooled cross-sectional path this todo describes -- `_compute_symbol_tf` (ic_engine.py:2790-
   2870) runs them through a bespoke per-symbol daily-cadence query instead
   (`WHERE fv.symbol = %(symbol)s`), so the n_symbols pseudo-replication bug does not apply to
   them. They have a *different* latent problem instead: 231 separate per-symbol significance
   tests run against what is structurally the same time series (the feature value is identical
   across symbols by definition), each entering BH-FDR independently via its own
   `cf_cluster_id` -- correlated multiple testing, not pseudo-replication. Not previously
   flagged; needs the same fix, folded into the unified path (item 4 below).
2. The other 20 broadcast features (calendar/session + 5 cross-asset) get zero special
   handling -- `_FEATURE_NAMES` (`[f.name for f in dataclasses.fields(FeatureVector)]`) includes
   them undifferentiated, and they flow into `_compute_cross_sectional_tf`/
   `_compute_one_cross_sectional_cell`, whose own docstring states the flawed assumption
   verbatim: *"each (bar_ts, symbol) pair is an independent observation."* This is the todo's
   bug, confirmed at the exact call site, for exactly these 20.
3. `concept_annotation` is NOT a valid home for the broadcast classification -- migration 225's
   own table comment is explicit: "no gate decision may read annotation content." Use
   `concept_registry.metadata` (JSONB, domain='feature', column already exists, no migration
   needed) instead -- a definitional property read directly by code, structurally different from
   an explanatory annotation.
4. `_compute_one_cross_sectional_cell` is fully vectorized across all 292 features in one
   `_subsample_and_rank` call per scale -- the trailing per-feature loop only unpacks results,
   it is not a compute loop. A broadcast feature needs a different row count (one per `bar_ts`,
   not one per `(bar_ts, symbol)`), which cannot share that matrix with per-symbol columns. Fix
   requires splitting `X_nd`'s feature columns into broadcast/per-symbol groups and running
   `_subsample_and_rank` twice per cell, merging results back by `feat_idx` -- same primitive,
   two constructions, not two test implementations.
5. `bar_ts` is fetched in `_compute_cross_sectional_tf`'s `chunk_sql` (`r[0]`) but explicitly
   dropped during accumulation (`X_acc.append_chunk` starts at `r[i+1]`) -- never reaches
   `_compute_one_cross_sectional_cell`. Collapsing broadcast rows to one-per-`bar_ts` requires
   threading `bar_ts` through the chunked fetch loop, `Float32ChunkAccumulator`, and the cell-
   compute signature. Confirmed each chunk is already bar_ts-contiguous (chunks are built from
   `ts_chunk`, a list of distinct bar_ts values, and each chunk's query pulls all symbols for
   that set), so the groupby-collapse itself is mechanically clean once `bar_ts` is retained --
   but this touches a function with a documented OOM history (float32 conversion exists
   specifically because this cell OOM'd at 20GB+ RSS, 2026-07-08 incident) and needs care.

**Blast radius:** `services/ic_engine.py` -- `_compute_cross_sectional_tf` (thread bar_ts
through fetch), `_compute_one_cross_sectional_cell` (column split, dual pass, merge), delete
`CONTEXT_FEATURES` frozenset, delete `_compute_symbol_tf`'s per-symbol daily-cadence block
(lines ~2790-2870, folded into the unified path). New: a lightweight variance-based broadcast
detector (cross-sectional variance ~= 0 per feature -- far simpler than `TagCalibrator`'s
OLS/HAC machinery) writing `concept_registry.metadata` for domain='feature' rows. One new APR
key: `alpha.ic.broadcast_variance_threshold`. Test sweep: `grep -r CONTEXT_FEATURES tests/`.
No migration required (metadata column reuse).

**Not a same-session patch.** Detector + registry write (~1-2 hrs) is cheap; the matrix-split
rewrite of `_compute_one_cross_sectional_cell` (~half day, the risky part given the OOM
history) is not. Any feature among the 23 currently showing `passes_fdr=true` in
`feature_ic_scores` must be treated as unproven until re-measured under the corrected test --
this changes a production significance gate, corpus-wide, not just this todo's own scope.
Given the blast radius, plan this as a proper phase (`/gsd-plan-phase`) rather than an inline
edit.

## Architecture reconsideration (2026-08-21) -- revises the 2026-08-11 decision

Re-examined under Renaissance-council rigor before kicking off phase planning. The 2026-08-11
decision ("one shared primitive, branch at sample construction") was right about WHAT to share
but wrong about WHERE: it forces broadcast-feature rows to be constructed inside the same
per-symbol cell (`_compute_one_cross_sectional_cell`), threading `bar_ts` through
`_compute_cross_sectional_tf`'s chunked accumulator -- the one with the 2026-07-08 OOM
incident -- purely so both column groups can share one matrix before being split back apart.
That's not reuse, it's coupling two different statistical computations at the wrong depth for
no benefit, and it's the exact "special case bolted onto shared infra" pattern this project's
own altitude-check discipline exists to catch.

**The deeper, previously unaddressed gap: no outcome variable was ever defined for a broadcast
feature's test.** A per-symbol feature's IC against that symbol's own forward return is
well-posed. A broadcast feature (`vix_z`, session flags, calendar cycles) carries zero
per-symbol information -- testing it against 231 individual symbols' returns isn't just
pseudo-replicated, it's the wrong outcome variable. What a broadcast feature can actually
explain is a market-level return: a cross-sectional aggregate (equal-weighted or cap-weighted
mean/median forward return across the active universe at that `bar_ts`). This aggregate-return
series does not exist anywhere in the codebase today.

**Revised recommendation:** do NOT merge broadcast into the per-symbol cell. Give it its own
small, separate cell (`_compute_one_broadcast_cell`) that reuses `_subsample_and_rank` as the
shared statistical kernel (confirmed fully row/column-agnostic -- it only needs `[n_sub,
n_features]` + a matching `returns_scale` vector, doesn't care what a "row" represents) but
builds a dramatically smaller input matrix: one row per `bar_ts` (feature values read from any
single representative symbol, since they're identical everywhere) against a new
market-aggregate-return column. This never touches the OOM-prone accumulator or needs `bar_ts`
threaded through the chunked fetch, and correctly frames broadcast features as the
market-timing signals they are rather than forcing them through per-symbol machinery built for
a different statistical object.

**Still an open call, not resolved unilaterally:** the aggregate-return definition itself
(equal-weighted vs. cap-weighted; full 231-symbol universe vs. the same regime-group subset
`ic_engine.py` already stratifies on). Routing to `/gsd-discuss-phase` to settle this before any
implementation, per user direction 2026-08-21.

## References

- `services/ic_engine.py`: `CONTEXT_FEATURES` (the 3 confirmed-broadcast macro features),
  `_compute_one_cross_sectional_cell` (the pooled cross-sectional significance test this gap
  affects)
- [203](../completed/203-canary-rng-seed-not-per-symbol-cross-sectional-pseudo-replication.md) --
  the canary-seed fix that surfaced this gap while verifying per-symbol pseudo-replication was
  fixed for the canary specifically; this todo generalizes the same concern to every broadcast
  feature, not just the canary.
