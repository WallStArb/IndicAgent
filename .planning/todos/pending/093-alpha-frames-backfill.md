# 093 — `alpha_frames` backfill (Phase 142B follow-through)

**Source:** Was tracked only as a bullet in `docs/research/2026-07-08-intelligence-lifecycle-
backlog-matrix.md`'s HIGH tier, not as a numbered todo — filed here 2026-07-10 so it isn't an
orphan invisible to the todo system (found while reconciling that matrix against
`.planning/todos/PRIORITIES.md`).

**Priority:** high — the standing concrete next step, not gated on anything.
**Effort:** S. **Risk:** low.
**Gate:** none. Does not need a corpus rebuild (upstream chain already correct).

## What's open

Phase 142B shipped `AlphaFrameWriter`/`CounterfactualTracker` complete 2026-07-10, but
`alpha_frames` still has **0 rows** — the writer has never actually been run.

Sequence:
1. `AlphaFrameWriter --backfill`
2. `CounterfactualTracker --backfill`
3. `CounterfactualTracker --evaluate-gate`

This is the concrete next step toward Phase 147's `alpha_frames` OOS-accumulation requirement,
and unblocks todos 078/082 (frame-outcome labels, additional simulation/validation lenses —
both currently in `deferred/` pending real closed frames existing).
