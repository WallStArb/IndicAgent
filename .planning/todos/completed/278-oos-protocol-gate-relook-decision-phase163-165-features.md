---
status: completed
priority: P1
filed: 2026-08-08
resolved: 2026-08-08
source: user-directed rigor review of the plan to refine single-security alpha using
  Phase 163-165 features; checked the plan against docs/plans/OOS-EVAL-PROTOCOL.md's
  own governance rule before any gate work starts
---

# Formal decision needed: does refining Phase 148's alpha_score with Phase 163-165
# features qualify for a legitimate OOS gate re-look, or would it be data-snooping
# against an already-used holdout?

## What

`docs/plans/OOS-EVAL-PROTOCOL.md`'s Cadence section is explicit: the authoritative OOS
gates run **at most once per construction**. Checked the plan to refine `alpha_score`
with Phase 163-165's features against the corrected-input re-look's 3-condition
exception — fails 2 of 3 (not independent of Gate 2's own disappointing result; "add
more features, try again," not a corrected instrument). Full detail in the original
filing (git history / `PRIORITIES.md`'s closure note).

## Resolution (2026-08-08)

**Decision recorded in `docs/plans/OOS-EVAL-PROTOCOL.md`'s Cadence section (dated
addendum, "New-construction decision, 2026-08-08").** Summary:

1. **Phase 148's original verdict stands permanently, unrevisited.** `gate1_signal`
   PASS / Gate 2 FAIL is not being re-tested. Refining raw `alpha_score` with more
   features and re-running the same gate would have been an ungoverned second look —
   correctly blocked.
2. **But todo 277 (resolved same session, alongside this one) changed what's actually
   being proposed.** `alpha_score` was found to be substantially a disguised common
   cross-sectional factor (100% same-direction at 15m/1h/1d); the real predictive signal,
   where it exists, lives in the residual after removing that common component per bar,
   not in the raw score. A construction that explicitly strips the common component is
   materially different from raw `alpha_score` — same category of difference as
   `cross_sectional_relative_value` was from the original per-symbol directional
   construction — not a tweak to the same one. **It is eligible for its own first look
   under a new `gate_id`, on its own merits.**
3. **That eligibility is conditional, not a green light.** Before any authoritative
   Gate 1/Gate 2 run under the new `gate_id`, the residual construction must first clear
   a properly-powered diagnostic-tier test (day-clustered bootstrap CI, shuffled-ranking
   null, BH-FDR) — todo 277's own number (`ic_residual=0.00453` at 15m) is a raw Pearson
   correlation with none of that rigor, informative but not sufficient. Mirrors exactly
   how `cross_sectional_relative_value` was validated: diagnostic script first,
   productionized service second, gate third.
4. **Explicitly flagged, not resolved**: whether the `2025-12-24` OOS boundary itself
   is due for a fresh cut given how many constructions have drawn against it (Phase 148
   x2, Phase 166 x2, Phase 167 x3). Bigger call, out of scope for this todo alone.

## Self-check performed before finalizing

Would "this is a new construction" have been argued if todo 277's residual finding had
come back null instead of small-positive? Reasoning stands independent of outcome
(cross-sectional demeaning to strip a dominant common factor is a principled technique,
not invented because Gate 2 failed) — but rather than trust that self-assessment alone,
the decision is enforced mechanically via the diagnostic-tier prerequisite in point 3,
not left as a judgment call that could be second-guessed later.

## Unblocks

The single-security alpha refinement plan can now proceed to a properly-powered
diagnostic-tier test of the residual construction at 15m (the only tf with OOS
`forward_returns` coverage) — day-clustered bootstrap, shuffled null, BH-FDR, same
discipline as everything else in this project. That test, not a Gate re-run, is the
correct next step. Not filed as its own todo yet — natural next action if the refinement
plan proceeds.
