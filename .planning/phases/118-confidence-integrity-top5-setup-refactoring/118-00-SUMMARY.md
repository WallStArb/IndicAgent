---
plan: "118-00"
phase: "118-confidence-integrity-top5-setup-refactoring"
status: complete
completed: "2026-06-09"
---

## Summary

Stripped all signal-extrinsic confidence modifiers from 12 I7 trading plugins via mechanical deletion. All four tasks complete.

## What Was Built

**Task 1** — Stripped HMM, CTF, and exhaustion from `ofi_continuation`, `gap_analysis_setup`, `cvd_divergence`.

**Task 2** — Stripped HMM from `failed_breakout`, `ofi_divergence`, `orb15`, `orb30`, `prev_day_level_test`. Also stripped missed `apply_exhaustion_boost` calls from `failed_breakout`, `orb15`, `orb30`, `prev_day_level_test`.

**Task 3** — Stripped HMM + CTF + exhaustion from `choch_reversal`, `supply_demand_setup`, `liquidity_sweep_reclaim`.

**Task 4** — Stripped zone/SMC/exhaustion/HMM/CTF from `liquidity_hunt` (most removals of any single plugin).

**Test cleanup** — Removed 7 test functions that tested the now-stripped extrinsic behavior (HMM gradient, exhaustion wiring tests for stripped plugins).

## Self-Check: PASSED

- Primary gate: zero `hmm_regime_weight`, `apply_exhaustion_boost`, `apply_exhaustion_guard` hits in confidence paths across all 12 files
- compose_confidence invariant: all 7 files that previously used it still route through it
- Unit tests: 9 pre-existing failures unchanged; no new failures introduced
- ruff: clean

## Key Files

- `src/intelligence/trading/ofi_continuation.py` — HMM + CTF + exhaustion_guard stripped
- `src/intelligence/trading/gap_analysis_setup.py` — HMM + exhaustion_boost stripped
- `src/intelligence/trading/cvd_divergence.py` — HMM + CTF stripped
- `src/intelligence/trading/failed_breakout.py` — HMM + exhaustion_boost stripped
- `src/intelligence/trading/orb15.py` — HMM + exhaustion_boost stripped
- `src/intelligence/trading/orb30.py` — HMM + exhaustion_boost stripped
- `src/intelligence/trading/prev_day_level_test.py` — HMM + exhaustion_boost stripped
- `src/intelligence/trading/choch_reversal.py` — HMM + CTF + exhaustion_boost stripped
- `src/intelligence/trading/supply_demand_setup.py` — HMM + CTF + exhaustion_boost stripped
- `src/intelligence/trading/liquidity_sweep_reclaim.py` — HMM + CTF + exhaustion_boost stripped
- `src/intelligence/trading/liquidity_hunt.py` — zone/SMC/exhaustion/HMM/CTF stripped

## Commits

- `refactor(118): strip extrinsic confidence modifiers from ofi_continuation, gap_analysis, cvd_divergence`
- `refactor(118): strip hmm_regime_weight from failed_breakout, ofi_divergence, orb15/30, prev_day_level_test`
- `refactor(118): strip extrinsic modifiers from choch_reversal, supply_demand_setup, liquidity_sweep_reclaim`
- `refactor(118): strip zone/SMC/exhaustion/HMM/CTF from liquidity_hunt confidence`
- `refactor(118): strip exhaustion_boost from failed_breakout, orb15/30, prev_day_level_test`
- `test(118): remove extrinsic-behavior tests invalidated by 118-00 strip`
