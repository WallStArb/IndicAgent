---
status: deferred
priority: P3
filed: 2026-07-21
source: found while fixing todo 162 (ATR-derived frame geometry's missing minimum
  stop-distance floor) -- cross-reference to Phase 163, not a bug
gate: Phase 163 (VP/SR Structural Primitives) executed and sr_support_dist/sr_resist_dist
  are real (non-NULL) in the live corpus
---

# Revisit whether frame geometry should become SR-aware once Phase 163 ships real S/R data

## Context

`compute_frame_geometry()` (`services/alpha_frame_writer.py`) is explicitly documented as
"ATR-only frame geometry — the sole target path; the support/resistance distance columns are
100% NULL across the corpus, so no conditional branch on them." That's not a permanent design
decision, it's a fallback forced by `sr_support_dist`/`sr_resist_dist` never having had real
data. Phase 163 (VP/SR Structural Primitives, currently PLANNED/not executed) closes todo 153
by implementing real computation for those two columns (plus `poc_dist_atr`/`va_position`) via
session-anchored VP/POC and rolling pivot-clustering support/resistance.

Todo 162 (ATR-derived stops producing extreme R-multiple outliers on thin-absolute-volatility
instruments, fixed same day as this todo was filed) added a data-integrity floor to the
*existing* ATR-only path — a narrow, independent fix that doesn't touch this question and
shouldn't be blocked on it. But once real S/R data exists, there's a legitimate, separate
design question worth asking deliberately rather than rediscovering from scratch:

**Should a stop ever be placed tighter than the nearest real support/resistance structure?**
And if so — does S/R override the ATR-derived stop, floor it, widen it, or just get logged as
a diagnostic alongside the existing geometry? This is a bigger call than todo 162's fix and
deserves its own scoping once the input data is real, not designed speculatively against null
columns today.

## Why deferred, not pending

Hard-gated on Phase 163 actually shipping — there's nothing to design against yet.
`sr_support_dist`/`sr_resist_dist` are 100% NULL until then; any design work now would be
speculative. Revisit once Phase 163 closes todo 153 and those columns have real values in
`feature_vectors`.

## References

- `services/alpha_frame_writer.py:64` (`compute_frame_geometry`, "the sole target path" comment)
- `.planning/todos/completed/162-atr-stop-distance-no-price-floor-extreme-r-multiples.md` — the
  narrow fix this is explicitly NOT trying to redo
- `.planning/phases/163-vp-sr-structural-primitives/163-CONTEXT.md` — Phase 163's own scope
  (closes todo 153, `sr_support_dist`/`sr_resist_dist` real computation)
