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
3. ~~`CounterfactualTracker --evaluate-gate`~~ — done 2026-07-12

## FRAME-04 baseline result (2026-07-12, pre-143.1-fix)

**Gate FAILS overall: 1/17 (tf, regime) cells pass.** Only `mid_bull/1d` clears
(`ci_lower=0.0196`, n=1,110 frames/537 clusters). All 16 other cells have `ci_lower <= 0`
(several deeply negative, `low_bull/5m` returned `ci_lower=NaN` on n=50/1 cluster — too thin to
resolve). Day-clustered block-bootstrap CI on GROSS `counterfactual_pnl_r`, per D-01.

**Not treated as alarming** — this run is against the *current* alpha_frames data, generated
before any of Phase 143.1's fixes landed: todo 094's sign-asymmetric eligibility (long-only
skew) and todo 091's CI miscalibration are both still live in the champion. A near-universal
FRAME-04 fail is consistent with, not contradictory to, the problems 143.1 is mid-fix on.

**Value going forward:** this is now the pre-fix baseline. Phase 143.1-08's champion (flag
OFF) vs challenger (flag ON, sign-symmetric) shadow comparison should re-run `--evaluate-gate`
on each weight_epoch and diff against this baseline — a real behavior check, not just "did the
flag flip something."

This unblocks todos 078/082 (frame-outcome labels, additional simulation/validation lenses —
both currently in `deferred/` pending real closed frames existing, which now exist) and
satisfies Phase 147's `alpha_frames` OOS-accumulation requirement's data precondition. **Todo
093 complete — move to `completed/`.**
