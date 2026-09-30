---
status: pending
priority: P1
filed: 2026-09-26
source: phase 183 session council review of the unified design against the research lane
---

# Research-lane dependencies phases 186 and 187 must carry

## What

1. **`repro_frozen.py` before the sleeve directory goes.** Design 14.1 deletes the
   `scripts/analysis/sleeve_walk_forward/` plumbing in phase 186. `repro_frozen.py` lives there
   and is the bit-identity check every research change runs, and the seed of the design's
   `determinism` tool (12.1). Promote it (and what it imports from that directory) into the
   research package or a tools module first; the deletion plan must list it.

   Progress: 2026-09-28, phase 186-03: promoted to
   `scripts/research/determinism/repro_frozen.py`; bit-identical on phase 179 S3 and phase 181
   S2/S3 (commit dc1985fc1); the sleeve directory deletion (186-16, 186-29) no longer blocks it.
   2026-09-30, 186-16: the old command `scripts/analysis/sleeve_walk_forward/repro_frozen.py` no
   longer exists; the bit-identity check is
   `python -m scripts.research.determinism.repro_frozen <scratch_out_dir>` (phase 183's D-16 and
   the multi-timeframe design's B7 guard run this), rerun bit-identical on the post-deletion tree.
2. **One source for E17 memory.** Phase 186's kernel registry declares each feature's memory.
   For feature members, that declared memory is `PredictorSource.memory`; with
   `Combiner.training_rows` (exists) and a `HorizonRule.reach` (kappa weight below 1e-3), one
   `book_memory()` sums them for the S3 guards, the shift diagnostic and the E17 lag (todo 442's
   L rule). Nobody types L by hand once this lands.
3. **One causality probe.** The `temporal_integrity` audit (truncate inputs at t, recompute,
   compare) is the same operation as the research S3 memory-reach guard. Build one probe over
   the pure `compute(inputs up to t)` entry point and use it in both.
4. **StepM through the E17 H0 battery.** Phase 187's selection resamples each attempt's D_s
   with a stationary bootstrap, which does not preserve the static weight times fbar_L error
   that oversizes E17's tail at large static cell means (todo 432). StepM runs through the
   battery (`scripts/research/e17_null_battery.py`, gating and diagnostic cells) before any
   selection uses it.

## Done when

Each item is in the phase 186 or 187 plan that owns it, or closed with a reason.
