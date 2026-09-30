---
status: completed
closed: 2026-09-30
priority: P3
filed: 2026-09-30
source: plan 186-13 review pass
---

# The regime kernel logs its skip events from inside a pure module

## What

`src/intelligence/features/kernels/_hmm.py` is documented as pure functions over arrays, but
`_walk_forward_hmm_full` and `walk_forward_family_arrays` log through structlog with a
`regime_writer.` event prefix (`regime_writer.walk_forward_hmm_convergence_iters`,
`regime_writer.<prefix>walk_forward_segment_skipped`). A kernel module names a service and does
I/O (logging), which the `pure_compute` invariant says to keep at the edges.

## Recommendation

Return the events as data: `FamilyResult` gains a `skipped` tuple (segment start and end, gate
info) and each segment dict already carries `converged`, iteration counts and gate info, so the
kernel reports them and `compute_regime_columns` passes them through. `services/regime_writer.py`
logs them with its own event names (the two names above are read by log queries, so keep them
there); the rebuild (186-25) logs or records them in its own way. Then drop `structlog` from
`_hmm.py`. The event names and fields do not change, so no dashboard or alert moves.

## Resolution (186-13 review pass, R3)

Done in the same phase. `FamilyResult.events` and `compute_regime_columns(...).events` carry `RegimeEvent`s; the kernel module imports no logger. `services/regime_writer.py` logs them with symbol and tf under the unchanged names (`regime_writer.walk_forward_hmm_convergence_iters`, `regime_writer.<prefix>walk_forward_segment_skipped`). The registry kernels return arrays only, so a rebuild that wants the lines calls `compute_regime_columns` and logs `events`.

## Why it was not done in the first pass

It changes the kernel's return type and every caller, and the pass that filed it held the
contract that kernel outputs and call signatures stay as they are. Do it with 186-25, which is
the second caller of `compute_regime_columns`.
