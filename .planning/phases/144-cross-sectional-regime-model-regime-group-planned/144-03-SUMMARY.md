---
phase: 144-cross-sectional-regime-model-regime-group-planned
plan: 03
subsystem: regime-signals
tags: [cross-sectional-regime, commodity, fx, disabled-on-ship]
dependency-graph:
  requires: []
  provides:
    - src/intelligence/regime_signals/commodity_momentum_ts.py
    - src/intelligence/regime_signals/fx_dollar_carry.py
  affects:
    - src/intelligence/regime_signals/__init__.py (Plan 04 registry, not touched here)
tech-stack:
  added: []
  patterns:
    - "compute()/build_tiers()/PROB_KEYS pure-function contract, DB-free signal modules"
    - "REFERENCE_SYMBOLS declaration for cross-group instrument dependencies (fx anchors on UUP/HYG, not peer members)"
key-files:
  created:
    - src/intelligence/regime_signals/commodity_momentum_ts.py
    - src/intelligence/regime_signals/fx_dollar_carry.py
    - tests/unit/test_regime_signals_commodity_momentum_ts.py
    - tests/unit/test_regime_signals_fx_dollar_carry.py
  modified: []
decisions:
  - "Fixed a flawed test fixture in the plan doc's own commodity_momentum_ts test: a linear price ramp (constant absolute increment) produces monotonically DECREASING log-returns, which correctly yields a negative momentum_z under the module's rolling-z design -- not a bug in the implementation. Replaced with an accelerating-growth fixture (deterministically increasing log-return sequence) that actually validates positive momentum."
metrics:
  duration: "~15 minutes"
  completed: "2026-07-12"
---

# Phase 144 Plan 03: Commodity/FX Disabled Signal Modules Summary

Built the two DISABLED-on-ship cross-sectional regime signal modules -- `commodity_momentum_ts.py`
(rolling log-return z-score + term-structure proxy across commodity ETF peer groups) and
`fx_dollar_carry.py` (UUP dollar-trend z-score + HYG carry-environment z-score) -- both pure,
DB-free functions matching the `compute()`/`build_tiers()`/`PROB_KEYS` REGISTRY contract used by
`breadth_vol.py`/`curve_credit.py` (built in sibling plans 01/02). Their `regime_group`s ship
`enabled: false` (commodity/fx enablement gated on todo 041's tag taxonomy audit), but the modules
themselves are built now for registry completeness ahead of Plan 04's dispatcher wiring.

## What Was Built

**`commodity_momentum_ts.py`** -- shared across `commodity_energy`/`commodity_metals`/
`commodity_agri` groups. Two signal dimensions: `momentum_z` (cross-sectional median of
per-symbol rolling log-return z-scores) and `ts_proxy` (cross-sectional median of price-slope
acceleration, an ETF-based contango/backwardation proxy). Tier vocabulary: `up_primary` /
`up_secondary` / `down_secondary` / `down_primary` (momentum) x `contango` / `neutral` /
`backwardation` (term-structure proxy) -- 4 momentum labels chosen deliberately over a 9-label
scale because commodity peer groups have only 4-8 instruments (sparse-bucket risk).

**`fx_dollar_carry.py`** -- two signal dimensions anchored on `REFERENCE_SYMBOLS = ("UUP", "HYG")`:
`dollar_z` (UUP rolling log-return z-score, dollar trend) and `carry_z` (HYG rolling log-return
z-score, risk-on/off proxy for carry). Tier vocabulary: `strong_dollar` / `weak_dollar` x
`risk_on` (implicit `risk_off` as the unlabeled complement). UUP/HYG are reference instruments
fetched regardless of peer-group membership -- Plan 04's dispatcher must add a
`_get_reference_symbols(module)` helper to fetch them alongside peer symbols.

Both modules were ported directly from `docs/plans/2026-07-01-cross-sectional-regime-model.md`
Tasks 6/7 per RESEARCH.md's confirmation that this code has "no drift issues" relative to the
live codebase (unlike `breadth_vol.py`, which needed the causal-rank/`_tf_window` port). No live
predecessor exists for either module -- this is new math, not an extraction.

## Tier Vocabulary Non-Overlap (Pitfall 4 invariant)

`feature_ic_scores` has no `regime_group` column -- group identity is implicit in `regime_label`
string uniqueness. Verified non-overlapping label components across all four groups:

| Group | Tier 1 | Tier 2 |
|-------|--------|--------|
| equity | low / mid / high | bear / neutral / bull |
| rates | steep / flat / inverted | wide / tight |
| commodity | up_primary / up_secondary / down_secondary / down_primary | contango / neutral / backwardation |
| fx | strong_dollar / weak_dollar | risk_on (+ implicit risk_off) |

Documented as a code comment in both new modules' docstrings and `build_tiers()` docstrings,
per the plan's acceptance criteria.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed a mathematically-flawed test fixture in `commodity_momentum_ts`'s
`test_rising_group_positive_median`**
- **Found during:** Task 1, initial test run after porting the plan doc's test file verbatim.
- **Issue:** The plan doc's test used a linear price ramp (`100 + i * 0.5`, constant absolute
  increment per bar) and asserted the resulting `momentum_z` median should be positive. This is
  mathematically incorrect: a linear price ramp produces monotonically DECREASING log-returns
  (diminishing percentage gain as price rises), so the module's rolling z-score of returns
  (current return vs. trailing-window mean/std) is correctly NEGATIVE for this fixture -- the
  implementation was right, the test's expected-value claim was wrong. Verified by hand
  computation: `z.iloc[window:].median() == -1.58` against the plan-doc-verbatim implementation.
- **Fix:** Replaced the fixture with a price series constructed from a deliberately increasing
  log-return sequence (`log_ret_ramp = arange(n) * 0.001`, prices reconstructed via
  `exp(cumsum(...))`), which genuinely exercises "recent momentum is stronger than the trailing
  window average" and produces a positive median z as intended.
- **Files modified:** `tests/unit/test_regime_signals_commodity_momentum_ts.py`
- **Commit:** `8785d667`

Also added one bonus test not in the plan doc's original file
(`test_empty_ref_bars_returns_none`, both modules) covering the module's documented `None`
early-return contract for empty/missing-reference input -- exercises existing behavior already
present in the ported `compute()`, no implementation change needed.

## Self-Check: PASSED

- `src/intelligence/regime_signals/commodity_momentum_ts.py` -- FOUND
- `src/intelligence/regime_signals/fx_dollar_carry.py` -- FOUND
- `tests/unit/test_regime_signals_commodity_momentum_ts.py` -- FOUND
- `tests/unit/test_regime_signals_fx_dollar_carry.py` -- FOUND
- Commit `8785d667` -- FOUND
- Commit `2f2cacdf` -- FOUND
- `.venv/bin/pytest tests/unit/test_regime_signals_commodity_momentum_ts.py tests/unit/test_regime_signals_fx_dollar_carry.py -v` -- 12/12 PASSED
- `grep "import psycopg2"` on both modules -- NOTHING (DB-free confirmed)
