---
status: pending
priority: P0
filed: 2026-07-21
source: found investigating 143.1-08's HOLD verdict -- "why aren't we finding reasonable
  short signals" led here, and this is the higher-leverage fix of the two found in that
  investigation (the other being todo 164, per-timeframe ensemble eligibility).
---

# Promotion gates test against one fixed OOS window -- structurally blind to any edge whose value concentrates in a regime that window doesn't contain

## What's wrong

`alpha.validation.oos_start = 2025-12-24` is a single fixed date. Every promotion decision
(143.1-08 included) evaluates its criteria (mean P&L CI lower bound, Sharpe, max drawdown)
against whatever regime that window happens to be in -- with zero regard for whether it's
representative of the regimes the strategy is meant to handle.

## Confirmed empirically, not theoretical

143.1-08's OOS window (2025-12-24 to 2026-07-07) was a +8.82% SPY rally. The full corpus
spans 2006-2026 and includes real crash windows -- COVID (-34.1%, Feb-Mar 2020) and the 2022
bear market (-23.4%). Short-frame performance by regime (`143.1-08-challenger`,
trimmed avg `counterfactual_pnl_r`, day-clustered N in parens):

| Period | SPY move | short avg pnl_r |
|---|---|---|
| COVID crash | -34.1% | **+0.0094** (23 days) |
| 2022 bear market | -23.4% | **-0.0039** (~breakeven, 185 days) |
| OOS window actually tested | +8.82% | **-0.0230** (131 days) |

Shorts made money during the real crash, were roughly breakeven through the 2022 bear
market, and lost money specifically during the window the promotion gate tested -- which was
a rally. The HOLD verdict answered "does this help in a rally" (no, unsurprising), not "does
this have real regime-conditional edge" (untested). This pattern likely isn't isolated to
143.1-08 -- check whether it affects Phase 144's D-05 acceptance gate and Phase 148's OOS
proof gates too, since they inherit the same `alpha.validation.oos_start` mechanism.

## Fix direction

Promotion criteria need to be evaluated regime-stratified, not against one blanket window.
Infrastructure to do this already exists and doesn't need building from scratch:

- Regime labels: `market_regimes`/`regime_group` (cross-sectional, Phase 144) or per-symbol
  HMM regime (`feature_vectors.regime`) -- either already computed and stored.
- Day-clustered bootstrap CI: already built for FRAME-04's exit gate
  (`counterfactual_tracker.py`'s `evaluate_frame_gate`) -- same day-clustering technique
  applies directly to a regime-stratified promotion criterion.

Real design decision needed (this is the part that needs a human call, not a mechanical
fix): how do per-regime results combine into a single promotion verdict? Options to weigh:
worst-regime gate (strategy must clear the bar in every regime it's exposed to -- strict,
may be too conservative), explicit regime-coverage requirement (must have adequate N in at
least N regimes, weighted differently per regime), or a weighted combination that doesn't
let one over-represented regime dominate the way the current single-window approach does by
construction. Whatever is chosen, apply it retroactively to re-evaluate 143.1-08's actual
HOLD verdict before treating it as final -- the verdict may change once tested against a
representative regime mix instead of one incidental window.

## References

- `alpha.validation.oos_start` APR key -- the single-window split point
- `.planning/milestones/v3.1-phases/143.1-measurement-and-eligibility-integrity-fisher-z-ci-bootstrap-/143.1-08-SHADOW-VALIDATION.md`
  -- the HOLD verdict this investigation followed up on
- `services/counterfactual_tracker.py`'s `evaluate_frame_gate` -- day-clustered bootstrap CI
  precedent to reuse, not reinvent
- `services/cross_sectional_regime_model.py` -- `market_regimes`/`regime_group` regime labels

## Closed 2026-07-21

Regime-stratified OOS gate shipped: `evaluate_frame_gate` generalized with a grouping-key +
coverage-floor parameter (`services/counterfactual_tracker.py`), wired into
`scripts/analysis/phase143_1_08_shadow_validation.py`'s C2/C7 criteria, new pre-registered
`alpha.validation.regime_gate_min_clusters` APR key (migration 244, seed 20). Design decision
made: worst-evaluated-cell gate (a cell below the day-cluster coverage floor is excluded from
the verdict combination rather than counted pass/fail) — not a full per-regime weighting
scheme, since coverage was too thin in most cells to support one.

Re-run against real 143.1-08 data: **verdict unchanged, still HOLD** — every cell with
adequate coverage (`n_clusters >= 20`) failed criterion 2 decisively for both champion and
challenger, so stratifying didn't change the outcome. Honest limit: 6 of 8 champion cells and
6 of 14 challenger cells had insufficient day-cluster coverage and were excluded from the
gate entirely, so this is a partial regime-by-regime verdict, not a complete one. Full output
in `143.1-08-SHADOW-VALIDATION.md` section 7.
