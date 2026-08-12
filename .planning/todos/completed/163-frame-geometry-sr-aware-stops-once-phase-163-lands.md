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

## RESOLVED 2026-07-23 — superseded by Phase 166's structural candidate mechanism

Phase 166 (Frame/Execution Recalibration) built exactly the mechanism this todo's design
question anticipated needing: `src/intelligence/trading/structural_confluence.py`
(`resolve_structural_zone`) resolves an effective stop distance from real S/R structure
(`sr_support_dist`/`sr_resist_dist` + VP confluence) when live data exists, falling back to the
pure ATR-derived stop (`tier="atr"`) when it doesn't — a concrete, empirically-testable answer
to "does S/R override, floor, or widen the ATR stop" (answer: it REPLACES the ATR-derived
distance with the resolved structural zone's bound on the stop side, wired via `AlphaFrameWriter`
`geometry_source=structural`, `services/alpha_frame_writer.py`'s `_resolve_structural_geometry`).

**The empirical question ("should a stop be placed tighter than real S/R structure — does it
help?") is NOT yet answered** — Phase 166's structural arm (`gate166_structural`) halted this
session because Phase 163 still has not executed (`sr_support_dist` remains 100% NULL,
unchanged from this todo's own filing). This is a valid, complete Phase 166 outcome (2 of 3
arms scored, structural correctly deferred rather than run against degenerate all-NULL data —
see verdict doc below), not a resolution of the underlying design question.

This todo is closed as a STANDALONE tracking item because Phase 166 already built the mechanism
and documented the exact resume path (run `/gsd-execute-phase 163`, re-verify
`sr_support_dist IS NOT NULL` count > 0, then run the structural arm's single remaining one-shot
gate cycle) — there is no separate design work left to scope; it collapsed into Phase 166's own
"Arm 3" resume point. Both the current champion (baseline, global ATR scalar, FAIL) and the
scalar candidate (per-(regime,tf) calibrated ATR scalar, FAIL, notably WORSE max drawdown) have
now been empirically tested and rejected — the structural candidate is the one remaining
untested hypothesis, and it stays open (via the resume path above), not closed by inference.

## References

- `services/alpha_frame_writer.py:64` (`compute_frame_geometry`, "the sole target path" comment)
- `.planning/todos/completed/162-atr-stop-distance-no-price-floor-extreme-r-multiples.md` — the
  narrow fix this is explicitly NOT trying to redo
- `.planning/phases/163-vp-sr-structural-primitives/163-CONTEXT.md` — Phase 163's own scope
  (closes todo 153, `sr_support_dist`/`sr_resist_dist` real computation)
- `docs/plans/archive/2026-07-23-phase166-frame-recalibration-verdict.md` — Phase 166's verdict doc,
  "Arm 3: Structural Candidate" section — the halt this todo's resolution cross-references, and
  the exact resume path for scoring the structural arm once Phase 163 executes
- `src/intelligence/trading/structural_confluence.py` — the confluence-resolution mechanism
  this todo's design question is now answered BY (mechanistically), pending real data to test it
