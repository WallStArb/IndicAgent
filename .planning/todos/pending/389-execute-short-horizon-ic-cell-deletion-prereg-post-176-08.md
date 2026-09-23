---
status: pending
priority: P2
filed: 2026-09-23
source: pre-registered this session after the recompute-cost re-derivation (todo 385) made the
  savings line concrete; evidence base is the 2026-09-13 TF-stack economics diagnostic
---

# Execute the short-horizon IC cell deletion (pre-registered, gated on post-176-08 window)

## What

Delete the structurally uneconomical short-horizon `ic_engine` cells via
`alpha.ic.active_scales.*` APR edits only (zero code), per the pre-registration at
`docs/research/ic-engine-short-horizon-cell-deletion-prereg.md` — read that first; it
owns the decision rule, consumer audit steps, and execution checklist. Expected ~31% of
per-symbol scale-cell compute (~2.7 → ~1.9 worker-hr/symbol), pending the rule's
measurement at execution.

## Gate

Phase 176-08's corpus recompute must complete first (its verdict must not straddle a
methodology change). Then bundle with todo 386 (+ threading/nogil if adopted from todo
385's lever benchmark) in ONE landing immediately before the next required recompute —
the whole-dict `active_scales` fingerprint hashing invalidates every surviving cell, so
the one-time cost must be absorbed by an already-required run, never standalone.
