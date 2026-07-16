---
status: pending
priority: P2
filed: 2026-07-16
source: todo 060's Cluster 2 legacy-doc review (intel-01/02/08) — the one concrete gap that
  survived cross-referencing the archived pre-v3.0 backlog against the live Feature Factory
---

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

## Not yet done

Nothing implemented — this is a gap flag only, not a design. Batch into a future Phase 151
atomic-primitives pass rather than a standalone phase; none of these are urgent on their own.

## References

- `docs/research/catalog.md` Cluster 2 section (full per-doc verdict table)
- `docs/research/archive/intel-01-momentum-acceleration.md`, `intel-02-second-derivative-indicators.md`,
  `intel-08-macro-cross-asset.md`
- `src/intelligence/feature_factory.py` — existing `_velocity` pattern (volatility family) and
  `vix_z`/`flight_quality`/`yield_slope_z` (macro family) to model the new fields on
- `.planning/todos/completed/060-review-cluster2-legacy-intelligence-backlog.md` — closing todo,
  full audit trail
