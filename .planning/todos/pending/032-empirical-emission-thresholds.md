---
**Created:** 2026-06-30
**Area:** intelligence
**Type:** correctness
**Priority:** P1
**Effort:** 2-3h (ensemble_trainer method + migration + one EnsembleBuilder run to verify)
**Benefit:** Replaces four researcher-set thresholds with data-driven values derived from actual ensemble IC and transaction cost estimates; eliminates a class of human judgment from the signal emission path
**Risk:** Low — additive method on EnsembleBuilder; thresholds written via APR (fully reversible)
**Gate:** todo 031 (gap-stratified IC) complete AND todo 030 (cost hurdle calibration) complete — both must reflect the same corpus state
---

# 032 — Empirical Emission Threshold Derivation

Second in the correctness gap execution chain. See design doc:
`docs/plans/2026-06-30-alphaengine-correctness-gaps.md`

## What

Add `_derive_emission_thresholds()` to `ensemble_trainer.py`. After each EnsembleBuilder
re-solve that changes ensemble IC by >= `alpha.ic.threshold_update_min_ic_change`, run a
threshold sweep: find the lowest alpha_score per tf where expected return (alpha_score ×
ensemble_ic) exceeds the cost estimate from APR. Write results to APR via ConfigService.

Current seeds (no empirical basis):
```
alpha.quant.threshold.5m  = 1.5
alpha.quant.threshold.15m = 1.2
alpha.quant.threshold.1h  = 1.0
alpha.quant.threshold.1d  = 0.8
```

## Files

- `services/ensemble_trainer.py`
  - Add `_derive_emission_thresholds(weight_version, ensemble_ic)` method
  - Call after weight write in the main solve path, guarded by ic_change >= threshold
- New migration:
  - INSERT `alpha.ic.threshold_update_min_ic_change = 0.15` into `config_schema` + `config_state`
  - INSERT `alpha.ic.threshold_sweep_min_n = 100` into `config_schema` + `config_state`

## Verification

1. Migration applies cleanly
2. `pytest tests/unit/ -q` green
3. Trigger a manual EnsembleBuilder run; confirm new threshold values appear in
   `config_history` with `changed_by='ensemble_builder'` and IC/cost logged in `reason`
4. Values are plausible — lower than seeds for liquid/frequent tfs, higher for noisier ones

## Unblocks

- todo 033 (decay monitor) — needs trustworthy weights and empirical thresholds before
  re-solve cycle is meaningful
