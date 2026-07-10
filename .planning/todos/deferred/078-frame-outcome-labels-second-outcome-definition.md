# 078 — Frame-outcome labels as a second outcome definition (post-142B)

**Status (moved to deferred/, 2026-07-10):** Hard-blocked on `alpha_frames` actually holding data -- Phase 142B shipped the writer/tracker machinery (2026-07-10) but the backfill run hasn't executed yet (0 rows as of 2026-07-10). Revive once alpha_frames has accumulated real closed frames.


**Source:** `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §6 (L3-3).
**Priority:** medium — diagnostic gold once available, but explicitly not a reason to touch
142B's frozen design now.
**Gate:** hard-blocked on Phase 142B (`alpha_frames`) shipping. Do not start before then.

## Proposal

142B's `alpha_frames` are triple-barrier labels in all but name (stop/target/hold-expiry with
exit-trigger priority). Once frames exist, register the frame outcome (barrier-hit sign,
counterfactual R) as a measurement target alongside fixed-horizon returns for the same events.
Fixed-horizon IC and path-aware outcome agreement/disagreement is diagnostic gold: a predictor
with horizon-IC but negative frame expectancy is being killed by path (stopped out before the
horizon pays) — an execution-geometry problem, not a signal problem, and the two are currently
indistinguishable.

## Mechanics

Pure read over `alpha_frames` × `alpha_events` after 142B ships. No new tables, reuses
pre-committed frame geometry entirely.
