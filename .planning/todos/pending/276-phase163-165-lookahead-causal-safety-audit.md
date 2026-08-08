---
status: pending
priority: P1
filed: 2026-08-08
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
