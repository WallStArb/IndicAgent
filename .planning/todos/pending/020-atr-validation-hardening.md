---
created: 2026-06-05T22:00:00.000Z
title: ATR Validation Hardening — Single-point injection in IntelligencePipeline
area: intelligence
files:
  - services/intelligence_pipeline.py
  - src/intelligence/atr_utils.py
  - docs/plans/atr-validation-hardening.md
---

## Problem

`get_atr_with_floor()` is now called 30× across I7 plugins after the signal data remediation migration. Each call re-derives ATR independently with a symbol argument. I1–I6 consumers use inconsistent silent fallbacks (`or 0.0`, `or 1`, `or 0.5`) which silently corrupt downstream confidence math.

## Action

Plan already written: `docs/plans/atr-validation-hardening.md`

1. `IntelligencePipeline` computes `atr_14_valid` once per bar after I1 merge and injects it into features.
2. Add `get_atr_valid(features)` to `atr_utils.py` — no symbol arg, no floor logic per-plugin. Raises if missing.
3. Migrate 30 I7 plugins from `get_atr_with_floor(features, symbol)` → `get_atr_valid(features)`.
4. Fix 5 I1–I6 consumers — replace silent fallbacks with `get_atr_valid()`.

## Notes

- Eliminates 30× redundant calls and all silent ATR fallbacks in one pass.
- The plan has been reviewed (REVIEWS file exists). Ready to execute.
