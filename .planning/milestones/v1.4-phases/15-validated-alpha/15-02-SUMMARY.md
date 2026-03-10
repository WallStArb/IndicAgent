---
phase: 15-validated-alpha
plan: "02"
subsystem: intelligence
tags: [derivative-oscillator, constance-brown, ema, rsi, composite, i2, tdd, validate-alpha]

requires:
  - phase: 15-01
    provides: validate_alpha.py statistical gate (Pearson r>0, p<0.05, N>=30) with --promote patching

provides:
  - DerivativeOscillatorPlugin (cmp_DerivativeOscillator) — triple-smoothed RSI derivative (EMA5→EMA3→SMA9 signal)
  - 8 unit tests covering outputs, warmup, cross detection, edge cases
  - Validation gate run recorded (FAIL — deferred, no live data yet; plugin not yet registered)

affects: [15-03, 15-04, 15-05, register_plugins, market_analysis_service]

tech-stack:
  added: []
  patterns:
    - "I2 composite dataclass pattern: EMA state always updates when input valid; output gate separate from state update"
    - "Warmup separation: len(sma9_buf) < 9 → return {} without blocking EMA convergence"
    - "crossover_detect(prev_ema3, ema3, prev_signal, signal_line) for cross flags stored per-bar in _state"

key-files:
  created:
    - src/intelligence/composites/derivative_oscillator.py
  modified: []

key-decisions:
  - "Validation gate deferred: plugin not registered so intelligence_features has zero rows for cmp_DerivativeOscillator; gate re-run after data accumulates"
  - "Do NOT manually patch register_plugins.py — only validate_alpha.py --promote may do this per plan constraint"
  - "EMA5 alpha = 2/(5+1) = 1/3, EMA3 alpha = 2/(3+1) = 1/2 — Constance Brown formula exactly"
  - "SMA9 uses deque(maxlen=9) for rolling mean; output gate: len(sma9_buf) < 9 → return {}"

patterns-established:
  - "I2 composite: reads from frames['features'] dict only — no raw OHLCV access"
  - "State update always runs when input is valid, even before output gate clears"

requirements-completed: [ALPHA-02]

duration: 15min
completed: 2026-03-07
---

# Phase 15 Plan 02: DerivativeOscillatorPlugin Summary

**Constance Brown Derivative Oscillator (EMA5→EMA3→SMA9 signal line) implemented as I2 composite plugin with 8 GREEN tests; validation gate deferred pending live data accumulation.**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-07T11:00:00Z
- **Completed:** 2026-03-07T11:15:00Z
- **Tasks:** 1 (Task 2: TDD GREEN — Task 1 RED was completed in prior session, commit 2021786)
- **Files modified:** 1 created

## Accomplishments

- Implemented `DerivativeOscillatorPlugin` following the exact I2 composite dataclass pattern from `macd_events.py`
- All 8 unit tests pass (outputs present, missing RSI guard, non-numeric guard, warmup separation, bullish cross, bearish cross, output types, no cross on stable)
- Ruff clean (0 errors)
- Validation gate run recorded: FAIL due to `n_total_bars=0` — plugin not yet registered so no live data in `intelligence_features`; registration deferred per plan constraint (only `--promote` may patch `register_plugins.py`)

## Task Commits

1. **Task 1: TDD RED (prior session)** - `2021786` (test)
2. **Task 2: TDD GREEN** - `a7777f1` (feat)

## Files Created/Modified

- `src/intelligence/composites/derivative_oscillator.py` — DerivativeOscillatorPlugin with EMA5→EMA3→SMA9 pipeline, crossover detection, module-level `plugin` singleton

## Decisions Made

- **Validation gate deferred**: `validate_alpha.py --plugin cmp_DerivativeOscillator --days 90` returned FAIL with `n_total_bars=0` because the plugin is not yet registered in `register_plugins.py` — `intelligence_features.i2` JSONB has no `deriv_osc_cross_bullish` field. Per plan constraint ("Do NOT manually patch register_plugins.py — only --promote may do this"), registration is deferred. Gate should be re-run once the plugin accumulates live data (requires a separate plan or manual `--promote` run after data exists).
- **Gate result recorded in** `docs/validation/2026-03-07-cmp_DerivativeOscillator-deriv_osc_cross_bullish.json`

## Deviations from Plan

None — plan executed exactly as written. Validation gate failure with deferred registration is the documented acceptable completion state B from the plan.

## Issues Encountered

- Pre-existing test failure in `tests/unit/config/test_settings.py::test_get_base_symbols` (VX not in base symbols) — unrelated to this plan, caused by `src/config/settings.py` changes from other in-progress work. Out-of-scope per deviation rules; logged to deferred items.

## Validation Gate Result

```json
{
  "plugin": "cmp_DerivativeOscillator",
  "field": "deriv_osc_cross_bullish",
  "run_at": "2026-03-07T10:53:01Z",
  "days": 90,
  "n_signal_bars": 0,
  "n_total_bars": 0,
  "verdict": "FAIL",
  "promoted": false
}
```

**Reason:** Plugin not registered → no `intelligence_features` rows with `i2.deriv_osc_cross_bullish`. Gate can be re-run via `python production/scripts/validate_alpha.py --plugin cmp_DerivativeOscillator --days 90 --promote` once data accumulates.

## Next Phase Readiness

- Plugin implementation is complete and tested — ready to promote once validation gate passes
- `validate_alpha.py --promote` will auto-patch `register_plugins.py` on passing gate run
- Phase 15 plans 03-05 can proceed independently (different plugins)

---
*Phase: 15-validated-alpha*
*Completed: 2026-03-07*
