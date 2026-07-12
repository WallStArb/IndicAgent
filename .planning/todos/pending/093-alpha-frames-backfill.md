# 093 — `alpha_frames` backfill (Phase 142B follow-through)

**Source:** Was tracked only as a bullet in `docs/research/2026-07-08-intelligence-lifecycle-
backlog-matrix.md`'s HIGH tier, not as a numbered todo — filed here 2026-07-10 so it isn't an
orphan invisible to the todo system (found while reconciling that matrix against
`.planning/todos/PRIORITIES.md`).

**Priority:** high — the standing concrete next step, not gated on anything.
**Effort:** S. **Risk:** low.
**Gate:** none. Does not need a corpus rebuild (upstream chain already correct).

## What's open

Phase 142B shipped `AlphaFrameWriter`/`CounterfactualTracker` complete 2026-07-10.

**Update 2026-07-12:** steps 1-2 are done — verified live via psql: `alpha_frames` has
11,813,874 rows, 2,639,074 with `counterfactual_pnl_r` populated (closed/scored frames).

Sequence:
1. ~~`AlphaFrameWriter --backfill`~~ — done
2. ~~`CounterfactualTracker --backfill`~~ — done
3. `CounterfactualTracker --evaluate-gate` — **still open.** Per 142B-02-SUMMARY.md's
   `<post_execution>` note, the FRAME-04 verdict was explicitly deferred at ship time and has
   never been run. It's a read-only CLI branch (no writes, no D-06 emission) — safe to run
   independent of the in-flight 143.1-07 corpus re-run.

This is the concrete next step toward Phase 147's `alpha_frames` OOS-accumulation requirement,
and unblocks todos 078/082 (frame-outcome labels, additional simulation/validation lenses —
both currently in `deferred/` pending real closed frames existing, which now exist).
