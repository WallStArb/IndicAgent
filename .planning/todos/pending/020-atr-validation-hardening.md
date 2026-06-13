---
created: 2026-06-05T22:00:00.000Z
title: ATR Validation Hardening — Single-point injection in IntelligencePipeline
area: intelligence
priority: 1
files:
  - services/intelligence_pipeline.py
  - src/intelligence/atr_utils.py
  - docs/plans/atr-validation-hardening.md
---

## Problem

Silent fallbacks (`or 0.0`, `or 1.0`) in ATR consumers corrupt downstream confidence math.

**Current state (2026-06-13):** Most cleanup was done — `get_atr_with_floor(features, symbol)` reduced from ~30 calls to 1 remaining (`zone_engine.py:232`). But `get_atr_valid()` was never created, so the plan is partially executed without the proposed clean API. Silent fallbacks still exist in `cross_tf_sr_confluence.py` (`or 1.0`) and `confluence_smc.py` (`or 0.0`).

## Action

Plan written: `docs/plans/atr-validation-hardening.md`

1. Add `get_atr_valid(features)` to `atr_utils.py` — raises if ATR is missing (no silent fallback).
2. Fix `zone_engine.py:232` — last remaining `get_atr_with_floor` call.
3. Fix `cross_tf_sr_confluence.py` (`or 1.0`) and `confluence_smc.py` (`or 0.0`) silent fallbacks.
4. Optionally: single-point injection in `IntelligencePipeline` per original plan.

## Notes

- Silent wrong answers are worse than loud crashes — the remaining `or 0.0` / `or 1.0` fallbacks must be replaced with `get_atr_valid()` raises.
- The plan has been reviewed (REVIEWS file exists). Scope is now much smaller than original.
