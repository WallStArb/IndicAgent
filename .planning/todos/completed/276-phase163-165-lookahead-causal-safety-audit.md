---
status: closed
priority: P1
filed: 2026-08-08
closed: 2026-08-21
source: user-directed rigor review ("think like a council of Renaissance senior
  engineers") of the plan to refine single-security alpha using Phase 163-165
  features; gates that plan, filed same session
---

# Phase 163/164/165's batch feature computations have never been audited for the same
# lookahead-leak failure mode that hit `ctf_momentum` and `regime_writer`'s HMM fit

## What

This project has found two independent lookahead/causal-safety bugs in the last two
weeks: `ctf_momentum`/`ctf_vwap_align`/`ctf_regime_align`'s batch-join lookahead
(todo 243, confirmed real, material — sign flips, Gate 1 PASS->FAIL) and
`regime_writer.py`'s HMM parameter fit on full history before causal decode (todo 248
/ Phase 171, confirmed real, currently being fixed in a concurrent session). CLAUDE.md's
own gotchas doc already warns "two independent incidents... don't make it three" for a
different bug class (batch-job performance investigations) — the same discipline
applies here.

Phase 163 (VP/SR Structural Primitives), Phase 164 (SMC Institutional Footprint
Primitives, 36 fields), and Phase 165 (Swing/Fib/Trend/Session Structure Primitives, 41
fields) are exactly the shape of computation prone to this bug class — backward-looking
structure detection over recent bars (order blocks, liquidity sweeps, swing
detection, fair-value gaps), computed in batch across a symbol's full history. None of
the three have had an explicit lookahead/causal-safety audit comparable to what caught
`ctf_momentum` (a code-review-driven join inspection) or `regime_writer` (a full-history-fit
vs. causal-decode structural argument).

Phase 164 in particular is currently cited as "the best-performing feature vintage in
the corpus" (72.2% FDR clear rate, `bsl_dist_atr`/`sweep_strength` showing
walk-forward-confirmed IC in bear regimes, 13 features already weighted into the live
shadow ensemble — see `project_v3_feature_port_raw_price_antipattern` memory). This is
precisely the "looks statistically overwhelming" signature `ctf_momentum` also had
(shuffled-null p=0.0000, n=24,924) before its leak was found. A good FDR rate is not
evidence of causal safety; it is equally consistent with a good real signal or an
undiscovered leak.

## Why now

Directly gates any plan to refine single-security (per-symbol directional) alpha using
these features — building a promotion decision on unaudited inputs repeats exactly the
mistake `ctf_momentum` already made once at real cost (a retracted Phase 167 "PASS,"
weeks of downstream work built on it). See [277](277-alpha-score-concentration-cofiring-degeneracy-diagnosis.md)
and [278](278-oos-protocol-gate-relook-decision-phase163-165-features.md) for the other
two gating items on the same plan.

## What to do

Read `services/backfill_feature_factory.py`'s (and any dedicated compute paths) actual
computation for Phase 163/164/165's fields, specifically: (1) any windowed/rolling
computation that could reach forward of the bar being computed (the same shape as
`ctf_momentum`'s HTF batch-join bug), (2) any full-series fit/calibration step analogous
to `regime_writer`'s HMM parameter fit (swing/fib pivot detection in particular —
`find_peaks`/`find_troughs`-style algorithms are a classic source of this: a "swing
high" is often only confirmable once N bars *after* it are known). Check both the live
per-bar path and the batch/historical-backfill path for parity (a live-safe algorithm
computed in batch over full history can still leak if the batch path doesn't replicate
the live path's causal windowing).

## Sizing

Investigation: medium — three phases' worth of computation logic, focused search for
one specific bug shape, not a full re-review. Fix, if found: unknown until scoped.

## Resolution (2026-08-21): CLEAN, closed

Audited both compute call sites (`compute()` live, `compute_batch()` batch/historical,
both in `src/intelligence/feature_factory.py`) against all three named risks.

1. **Windowed reads reaching forward (the `ctf_momentum` shape)** — every Phase
   163/164/165 `_compute_*` function in `compute_batch` is called against an explicit
   `arr[start : i + 1]` pre-slice (`start = max(0, i - lookback + 1)`), never the full
   series, at every call site checked: VP/SR (`_compute_sr_dist_atr`, `_derive_session_vp`),
   SMC (`_compute_order_blocks`, `_compute_fvg`, `_compute_liquidity_sweeps`,
   `_compute_liquidity_pools`, `_compute_supply_demand_zones`, `_compute_bos_choch`), and
   swing/trend/fib (`_compute_swing_structure`, `_compute_trend_structure`,
   `_compute_swing_momentum`, `_compute_fib_zones`). Each call site carries an inline
   comment stating the causal pre-slice is deliberate. `compute()` (live) passes the full
   rolling-history buffer, which by construction of streaming ingestion never contains
   anything beyond "now" — window-length semantics match between the two paths.
2. **Full-series fit/calibration (the `regime_writer` HMM shape)** — none found. Every
   function here is a deterministic, stateless geometric/windowed calculation; nothing
   estimates parameters from full history before applying them causally.
3. **Pivot-detection lookahead (`find_peaks`/`find_troughs`)** — checked both
   `src/intelligence/utils/core.py`'s implementations and the independent
   `_detect_swing_extremes` (feature_factory.py, deliberately not reusing
   find_peaks/find_troughs per its own "D-06 Finding B" docstring). Both require `n`
   bars on both sides to confirm a peak/trough, mathematically capping the last-returnable
   index at `len(array) - n - 1` — combined with the causal pre-slice, a "confirmed" swing
   high/low is always at least `n` bars stale relative to the current bar. This is enforced
   by the math, not just convention; `swing_high_age_bars`/`swing_low_age_bars` is the
   observable proof the lag is real and non-zero.

Also confirmed `compute_batch`'s per-symbol loop iterates in strict ascending `bar_ts`
order, so `FeatureCache` mutations (`update_session_levels`, `update_overnight_range`)
accumulate in correct chronological order in both paths.

**Scope boundary, not a gap**: this checked the windowing/slicing mechanism — the
specific bug class both prior incidents (`ctf_momentum`, `regime_writer`) were — at every
Phase 163/164/165 call site, not a full line-by-line re-review of every internal branch
(e.g., whether `_compute_bos_choch`'s break-of-structure logic has some unrelated bug).
That matches this todo's own scoping ("focused search for one specific bug shape, not a
full re-review").

**Notable**: this causal-safety discipline in Phase 163-165 (completed 2026-07-28)
predates the `ctf_momentum` leak's discovery (~2026-08-05) — it wasn't a retrofit,
whoever built these phases already had this discipline independently.

Closes one of three gating items for the single-security alpha refinement plan
(alongside [277](../completed/277-alpha-score-concentration-cofiring-degeneracy-diagnosis.md)/
[278](../completed/278-oos-protocol-gate-relook-decision-phase163-165-features.md), both
already closed) — all three now clear.
