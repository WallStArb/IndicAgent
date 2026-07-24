---
status: completed
priority: P2
filed: 2026-07-16
closed: 2026-07-24
source: todo 060's Cluster 2 legacy-doc review (intel-01/02/08) — the one concrete gap that
  survived cross-referencing the archived pre-v3.0 backlog against the live Feature Factory
---

**Closed 2026-07-24 — content fully captured in `/gsd-plan-phase 151`.** All 4 candidates
(under the Fable-reviewed names below) are built exactly as reframed here: velocity/VWAP in
`151-01-PLAN.md` (Wave 1), macro spreads + stock-bond correlation in `151-04-PLAN.md` (Wave 3).
One correction beyond this todo's own review: the `macro.sb_corr.*` APR namespace proposed below
is not sanctioned in CLAUDE.md — those keys ship under `feature.*` instead (see ROADMAP.md's
Phase 151 "Planning-time decisions recorded"). Remaining work (build + IC screen) tracked under
Phase 151, not this todo.

# Momentum-oscillator velocity feature + two now-unblocked macro spreads

## Finding

Closing todo 060 (review of 5 archived pre-v3.0 intel docs against `src/intelligence/feature_factory.py`,
see `docs/research/catalog.md`'s Cluster 2 section, 2026-07-16) confirmed nearly everything in
those docs is superseded — except three concrete, cheap Phase 151 atomic-primitive candidates:

1. **Momentum-oscillator velocity/curvature feature** — Feature Factory already ships a
   `_velocity` pattern for volatility estimators (`parkinson_vol_velocity`,
   `garman_klass_vol_velocity`, `yang_zhang_vol_velocity`, `vol_velocity_z`), but no equivalent
   exists for momentum oscillators. intel-01/intel-02 both proposed acceleration/inflection
   signals on RSI/MACD-style momentum; the existing `momentum_z_fast/mid/slow` z-scored return
   family has no rate-of-change field built on top of it. Concrete candidate: a
   `momentum_z_velocity` (or per-window `momentum_z_velocity_fast/mid/slow`), same construction
   as the volatility `_velocity` fields (Δ of the underlying z-score over one bar or a short
   window).
2. **VWAP acceleration** — no Δ`vwap_dev_sigma` field exists; same cheap velocity pattern.
3. **Two now-unblocked macro spreads (from intel-08):** "real yields" (TIP/TLT) and "credit
   spread" (HYG/LQD) were deferred in intel-08 (2026-06-14) as blocked on data availability.
   `TIP`, `HYG`, `LQD` are all live in the current 80-instrument universe (58→80 ETF expansion,
   2026-07-01, postdates that doc) — both are now buildable using the identical pattern already
   proven for `vix_z`/`flight_quality`/`yield_slope_z`. Stock-bond correlation (`sb_corr_30/60/z`,
   using existing `TLT`/`SPY`) is also now buildable, no new subscription needed.

## Fable review (2026-07-24, same pattern as todo 104/180)

Dispatched alongside todo 180's review since this todo had never been independently checked.
Grounded directly against live `feature_registry` (135 tier-0/8 tier-1/29 tier-2 rows) and
`feature_cache.py`. Key precedent the review found: `flight_quality` (TLT/SPY divergence) is
`tier=2_theory` — its own code comment bakes in "positive = risk-off," a market-theory claim —
while the mechanically identical `yield_slope_z` (TLT/SHY ratio, z-scored, no directional label)
sits at `tier=0_atomic`. The registry already draws exactly the line this todo's spreads need to
respect. Verdict per candidate:

1. **`momentum_z_velocity` — KEEP tier-0, reframe as the todo's own parenthetical
   `momentum_z_velocity_fast/mid/slow`** (make it the actual spec, mirroring the 3-estimator
   `_velocity` pattern exactly, not a single field). Confirmed non-redundant. **Needs a new APR
   key** for the delta-lag/window (mirror `feature.vol_velocity.window`), e.g.
   `feature.momentum_velocity.window` — don't hardcode the bar-lag.
2. **VWAP "acceleration" — REFRAME name only.** A single first difference is a *velocity*, not
   an *acceleration* (2nd derivative); nothing in the existing pattern uses "acceleration" for a
   1st-order delta. **Rename to `vwap_dev_sigma_velocity`.** Tier-0, non-redundant. Needs its
   own APR delta-window key, same as #1.
3. **"Real yield spread" (TIP/TLT), "credit spread" (HYG/LQD) — KEEP tier-0 conditionally,
   REFRAME names.** Must be built like `yield_slope_z` (z-scored ratio, no directional label),
   not like `flight_quality` (theory-laden sign interpretation). The proposed names smuggle in
   finance theory — "real yield" and "credit spread" both assert a specific causal referent that
   the feature itself doesn't compute (no inflation-expectations or default-risk term is
   actually in the formula, just a price ratio). **Rename to instrument-descriptive form**
   matching `yield_slope_z`'s convention: `tip_tlt_ret_z`, `hyg_lqd_ret_z`. **Needs an APR
   z-score-window key per spread** (mirror `vix_zscore_window`).
4. **`sb_corr_30/60/z` — REFRAME naming, tier-0 upheld.** A rolling correlation coefficient is
   theory-free, same class as `hurst_exponent`/`skewness` (glossary's own canonical primitive
   examples) — it reports a statistical property, doesn't assert what it means. But `30`/`60`
   are tunable window lengths, not the statistic itself — violates naming-system.md §7 (contrast
   the allowed `momentum_z_5`, where `5` IS the statistic, not a calibration knob). **Rename to
   `sb_corr_fast`/`sb_corr_slow`/`sb_corr_z`**; move day-counts to **new APR keys**
   `macro.sb_corr.window_fast`/`macro.sb_corr.window_slow` (no equivalent exists yet).

## Not yet done

Nothing implemented — this is a gap flag only, not a design (naming/tier now corrected above,
but no formula finalized, no IC pre-screen run). Batch into a future Phase 151 atomic-primitives
pass rather than a standalone phase; none of these are urgent on their own.

## References

- `docs/research/catalog.md` Cluster 2 section (full per-doc verdict table)
- `docs/research/archive/intel-01-momentum-acceleration.md`, `intel-02-second-derivative-indicators.md`,
  `intel-08-macro-cross-asset.md`
- `src/intelligence/feature_factory.py` — existing `_velocity` pattern (volatility family) and
  `vix_z`/`flight_quality`/`yield_slope_z` (macro family) to model the new fields on
- `.planning/todos/completed/060-review-cluster2-legacy-intelligence-backlog.md` — closing todo,
  full audit trail
