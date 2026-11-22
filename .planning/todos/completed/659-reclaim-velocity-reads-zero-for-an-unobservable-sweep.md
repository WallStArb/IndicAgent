---
status: completed
priority: P1
filed: 2026-11-22
source: indicagent-f6, todo 652 trace and independent review
owner: lead
---

# reclaim_velocity reads 0.0 where the value is unmeasured

## What

When the latest sweep is within reclaim_bars of the window end, the reclaim cannot be observed yet, but reclaimed stays 0.0 and the velocity reads 0.0. Location: src/intelligence/features/kernels/smc.py lines 550-581. It should return NaN (object absent or unobservable), never 0.0.

## Constraint

The fix moves stored values and the rebuild code key, so it lands before the 1d-first corpus run, not after. Then declare the column zero_is_state only for its genuine measured 0.0 (see the kernel property declarations in 5c8461d81 and todo 652).

## Done when

The kernel returns NaN on that branch, a test pins it, the unit suite exits 0, the code key change is reported, and the 652 pilot screen G3 no longer fails the column.

## Closure (2026-11-22)

`_compute_liquidity_sweeps` returns `reclaim_velocity` None while the reclaim window is still open and every observed bar held; 0.0 only for a reclaim observed to fail (a close at or through the swept level) or a completed window that did not hold. The two sweep loops share one `_reclaim_velocity` helper. The column is declared `zero_is_state` for that measured 0.0. Pinned by `test_pp_open_reclaim_window_reads_none_not_zero` and `test_pp_reclaim_velocity_breaks_to_zero_on_a_close_through_or_at_the_swept_high` (the independent review caught a close-equals-swept-high regression in the first version; the second test pins it). Stored values and `rebuild_code_key()` move; the production golden changes only in `reclaim_velocity`, one column in each of the 16 stored real cases.
