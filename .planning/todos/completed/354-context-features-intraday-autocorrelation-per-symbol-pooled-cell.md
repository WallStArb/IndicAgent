---
status: closed
priority: P0
filed: 2026-08-25
closed: 2026-08-26
source: Phase 173 Plan 02 (173-02-PLAN.md Task 2) -- surfaced while deleting ic_engine.py's
  bespoke CONTEXT_FEATURES daily-cadence significance path
---

# vix_z/yield_slope_z/flight_quality now measured only via per-symbol intraday duplication --
# temporal pseudo-replication, a different bug than the one Phase 173 fixes

## What

Phase 173 Plan 02 deleted `ic_engine.py`'s bespoke daily-cadence significance path for
`vix_z`/`yield_slope_z`/`flight_quality` (the `CONTEXT_FEATURES` frozenset and its
`context_features`-table query inside `_compute_symbol_tf`). Before the deletion, that path
existed specifically to avoid measuring these three macro features from `feature_vectors`
directly, because doing so means one daily value gets duplicated across every intraday bar of
that day -- ~78x at 5m, ~26x at 15m, ~6.5x at 1h. The deleted block's own comment documented
this exact reason for its existence:

> Measuring IC from feature_vectors would inflate IC via artificial autocorrelation (same daily
> value duplicated ~78 times for 5m TF).

**Pre-deletion gate result (proves the deletion itself dropped no live measurement):** a live
query run immediately before the deletion (2026-08-25T16:02:30Z) returned
`SELECT count(*) FROM feature_ic_scores WHERE regime_label_source='context_features'` = **0**.
The daily-cadence path had zero live rows at deletion time -- this todo is not about lost data,
it is about the code path these three features now fall back to.

With the daily-cadence path gone, `vix_z`/`yield_slope_z`/`flight_quality` are measured
**only** through `_compute_symbol_tf`'s ordinary intraday per-symbol path (reading the columns
directly off `feature_vectors`, same as any per-symbol-varying feature). That path has no
daily-deduplication step -- it treats each intraday bar as an independent observation of
whatever value `feature_vectors` carries for that bar, which for these three columns is the
same value repeated for every bar of the trading day. This inflates effective N by the same
duplication factor the deleted comment warned about, in the per-symbol pooled cell.

## Why this is a DIFFERENT bug than the one Phase 173 fixes

Phase 173's own broadcast-cell mechanism (Plans 03/04) fixes **cross-sectional pseudo-
replication** -- independence assumed across SYMBOLS at a single `bar_ts`, when a broadcast
feature's value is identical across every symbol in the pool. That fix builds a dedicated
broadcast cell against an equal-weighted market-aggregate return, explicitly for the
cross-sectional path (`_compute_cross_sectional_tf` / `_compute_one_cross_sectional_cell`).

This todo is **temporal pseudo-replication** -- independence assumed across BARS within a
single symbol's own intraday time series, when the feature's value is constant across every
bar of a trading day. It lives in the per-symbol pooled path (`_compute_symbol_tf`), a
different cell, a different axis of non-independence. **The Phase 173 broadcast cell does NOT
cover this path.** Fixing cross-sectional pseudo-replication does nothing for temporal
pseudo-replication in the per-symbol cell; they are orthogonal bugs that happen to share the
same three feature names as their most visible instance.

## Proposed fix (not implemented here)

A temporal-decimation stride for broadcast features specifically inside the per-symbol pooled
cell -- analogous to the existing `subsample_min_stride` mechanism (`alpha.ic.subsample_min_stride`
APR key, `services/ic_engine.py`), which already exists to counter a related (but not identical)
over-counting problem for ordinary per-symbol features. The natural shape: detect
broadcast-classified features (via `concept_registry.metadata->>'broadcast'`, the same
classification source Phase 173's cross-sectional fix reads) inside `_compute_symbol_tf`, and
for those features only, subsample to roughly one observation per calendar day rather than the
feature's own native `subsample_min_stride` bar-count stride -- mirroring the deleted
daily-cadence path's `DISTINCT ON (DATE(bar_ts))` logic, but sourced from `feature_vectors`
directly instead of a separate `context_features` table.

## Scope

Not fixed by this todo's filing, and not in scope for Phase 173 (confirmed via Plan 02's own
`must_haves` truths -- deletion was gated on proving zero rows lost, not on immediately
replacing the deleted mechanism with an equivalent one). File for future prioritization.

## Fixed, 2026-08-26

Implemented substantially as proposed above, with two real design corrections found during
implementation (not present in the original proposal) and one scope narrowing forced by a
live-data check -- all three caught before shipping, not after.

**Architecture:** `services/ic_engine.py` gained `_compute_one_symbol_broadcast_cell` (mirrors
the already-shipped cross-sectional `_compute_one_broadcast_cell`'s pattern, but collapses by
CALENDAR DAY within one symbol's own time series instead of by `bar_ts` across symbols -- picks
the first bar of each day as representative, correlates that bar's own feature value and own
forward return, no cross-row aggregation needed since there's no peer-symbol dimension here).
`_compute_one_regime_cell` gained an optional `broadcast_mask` param (default `None` = zero
behavior change for every pre-existing caller) that excludes broadcast columns from its own
per-bar measurement, mirroring the exact pattern Phase 173 already used on
`_compute_one_cross_sectional_cell`.

**Design correction #1 (found during implementation, not in the original proposal):**
day-decimation alone is NOT sufficient embargo separation for every scale. 1h's `slow`/
`extended` scales (`lookahead_bars`=20/60) exceed 1h's own ~7 bars/trading-day -- two
day-representative observations only 1 day apart would still have heavily overlapping
forward-return windows for those two scales. Fix: per-scale `day_stride =
ceil(lookahead_bars / broadcast_max_bars_per_day[tf])` generalizes the existing `scale_stride`
mechanism to day granularity. New APR keys (`alpha.ic.broadcast_max_bars_per_day.{5m,15m,1h}`,
migration 325, `[conventional]`: NYSE 6.5hr session / bar duration, cross-checked against 2
years of real SPY data before seeding -- exact match). Verified directly against real 1h SPY
data: `slow` day_stride=3 -> n_independent 4861->1620 (≈4861/3), `extended` day_stride=9 ->
539 (≈4861/9), both matching the formula almost exactly.

**Design correction #2 (independent review, caught before shipping, see below):**
`embargo_bars`/`bootstrap_block_size` passed to `_subsample_and_rank` must be expressed in
ROW-INDEX units of the day-strided array, not raw bar counts -- the sibling per-bar cells'
convention (`embargo_bars=lookahead_bars`, `bootstrap_block_size=config.bootstrap_block_size[tf]`
directly) is calibrated for arrays where each row is ~1 raw bar apart; blindly reusing it on an
array where each row is ~`day_stride` TRADING DAYS apart would over-embargo by ~`day_stride`x
(silently starving walk-forward folds on smaller real cells) and size bootstrap blocks at
~`day_stride`x too many trading days each (few, huge blocks -> understated standard errors ->
falsely narrow/significant CIs -- reintroducing overstated significance through a different
mechanism than the one this whole fix exists to close). Fixed: `embargo_bars=1` (day_stride's
own ceiling-division construction already guarantees adjacent rows don't overlap, so 1 row is a
minimal non-zero safety margin, not an arbitrary constant); `bootstrap_block_size=max(1,
config.bootstrap_block_size[tf] // max_bars_per_day)` (`[initial_estimate]`, directionally
correct via the same conversion shape as `day_stride` itself, not independently re-tuned via a
dedicated autocorrelation study).

**Design correction #3 (independent review, caught before shipping):** 1d has no duplication to
correct at all -- one 1d bar already equals one trading day, so `_TEMPORAL_BROADCAST_FEATURE_NAMES`'s
features are already measured correctly, once per day, by the ordinary per-bar path there.
Routing 1d through the day-decimated path anyway would be both unnecessary AND actively wrong
for its own `slow` scale (`broadcast_max_bars_per_day_for("1d")`'s large sentinel forces
`day_stride=1` regardless of `lookahead_bars`, providing zero real separation at 1d granularity
for a scale whose `lookahead_bars > 1`). Fixed: `_compute_symbol_tf`'s `broadcast_mask`
construction gates on `tf in config.broadcast_max_bars_per_day` (only the 3 affected intraday
tfs have keys). Verified directly: a real 1d/SPY run emits exactly 2 `vix_z` rows (fast + slow,
one per active scale) with `n_independent` matching the ordinary per-bar count exactly, no
broadcast-path duplicate.

**Scope narrowing (live DB check, the most consequential finding of the session):** the
original proposal (and this todo's own "Proposed fix" section above) suggested detecting
broadcast-classified features via `concept_registry.metadata->>'broadcast'` -- the SAME
classification Phase 173's cross-sectional fix reads. Live DB verification caught this as wrong
before it shipped: that flag covers ~38 features (not just the 3 named in this todo's title),
and most of the other 35 (calendar/session encodings like `hour_of_day_cos`, `amd_phase`,
cross-asset ratios) are genuinely intraday-varying, NOT day-constant --
`hour_of_day_cos` empirically has 78 distinct values across one real trading day (AAPL/5m,
2024-06-03). Using the full set would have either silently dropped real per-bar signal from
`_compute_one_regime_cell` or crashed `_compute_one_symbol_broadcast_cell`'s within-day
invariance guard outright on live data. Fixed: a new, small, explicitly-documented
`_TEMPORAL_BROADCAST_FEATURE_NAMES = frozenset({"vix_z", "yield_slope_z", "flight_quality"})`
constant, intersected with `broadcast_features` (not used alone -- the intersection is a
deliberate fail-safe: if concept_registry ever unflags one of these 3, this fix also stops
applying to it). Widening this set to the rest of concept_registry's `broadcast=true` features
needs its own empirical within-day-variance classifier, not a hand-expanded list -- filed as
[360](pending/360-broadcast-day-constant-empirical-classifier.md).

**Validation:** 18 new unit tests (`tests/unit/test_ic_engine_compute_split.py`) covering
day-grouping (no-sort/no-unique discipline), the `day_stride` formula (both the no-op case at
5m/15m and the reduction case at 1h), the embargo/bootstrap-block-size day-unit conversion, the
within-day invariance guard (violation + all-NaN-does-not-trip), backward-compatibility
(`broadcast_mask=None` bit-identical to an explicit all-False mask on `_compute_one_regime_cell`),
feature exclusion from `_compute_one_regime_cell`'s emission, the allowlist-intersection
construction, and the `1d` exclusion gate. Live end-to-end smoke tests against real AAPL/5m and
SPY/1h/1d production data (not just synthetic fixtures) at every stage -- caught the scope bug
and confirmed all three design corrections empirically, not just via unit tests. Independent
review: Codex hit its usage limit mid-review (no verdict); AGY (Antigravity) found the 3 real
issues behind design corrections #2 and #3, all fixed and re-verified against live data before
closing. Full `tests/unit/` suite green, ruff/black clean.

**Not built here, tracked separately:** [360](pending/360-broadcast-day-constant-empirical-classifier.md)
(empirical classifier to widen the allowlist beyond 3 names).
