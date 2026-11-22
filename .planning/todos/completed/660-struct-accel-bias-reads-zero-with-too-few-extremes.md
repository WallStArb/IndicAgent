---
status: completed
priority: P1
filed: 2026-11-22
source: indicagent-f6, todo 652 trace and independent review
owner: lead
---

# struct_accel_bias reads 0.0 where the value is unmeasured

## What

With fewer than two retained highs or lows the bias is 0.0, the same value as the genuine mixed-structure state. Location: src/intelligence/features/kernels/vp_sr.py about line 912. It should return NaN (object absent or unobservable), never 0.0.

## Constraint

The fix moves stored values and the rebuild code key, so it lands before the 1d-first corpus run, not after. Then declare the column zero_is_state only for its genuine measured 0.0 (see the kernel property declarations in 5c8461d81 and todo 652).

## Done when

The kernel returns NaN on that branch, a test pins it, the unit suite exits 0, the code key change is reported, and the 652 pilot screen G3 no longer fails the column.

## Closure (2026-11-22)

`struct_accel_bias` is None with fewer than two retained highs or lows; 0.0 only for a measured mixed structure (highs and lows disagree), declared `zero_is_state`. Pinned by `test_struct_accel_bias_is_none_with_too_few_extremes_and_zero_for_mixed_structure`. The stored real cases of the production golden never hit the under-two branch, so no golden digest moves for this column; `rebuild_code_key()` still moves with the kernel edit.
