# 153 — Apply shrink_ic() before the E1/E2 champion judgment renders a verdict

**Source:** `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §7 (L4-3),
concretizes `docs/research/measurement-ic-engine.md` Open Question 7.
**Priority:** MEDIUM (downgraded from HIGH) — the time-sensitive interim step is done; what's
left is a real design decision, not an urgent blocker.
**Gate:** none for the interim step (done). The full fix needs an operator/design decision on
the peer-group question below before it can be implemented.

**Status (2026-07-08): interim fallback implemented, full fix still open.** OQ7 itself is
explicit that "the open work is choosing the peer group for variants, not writing the math" —
`shrink_ic()` is grain-agnostic and ready, but which peer group E1/E2/E3/E4 variants should
shrink toward (across strata for the same variant? across variants within a stratum? something
else?) is a genuine unresolved methodology question, not something to invent under time
pressure. Implemented the doc's own sanctioned minimum instead: `ops_ensemble_weight_compare.py`
now tags every WIN verdict with a D-15 winner's-curse caveat (commit `ac9e7f25`, tests in
`tests/unit/test_ensemble_weight_compare.py`) so a selection-biased IC is never read as
unbiased. **This todo stays open** for the actual peer-group design decision + shrinkage
implementation — that part still needs a real call, ideally before a champion promoted under
the caveated verdict sees much use.

## Problem

The pending E1 (shrunk-IC)/E2 (mean-variance Σ⁻¹·IC) A/B judgment selects a champion per
stratum without shrinking the winner's measured IC. Selecting the best of several noisy
estimates and then reporting its raw measured value overstates it (winner's-curse / selection
bias) — the same logic that already motivates E1's shrinkage of *inputs*, just not yet applied
to the *selection* step itself.

## Fix

`shrink_ic()` (already built, grain-agnostic — see `src/intelligence/ensemble/` or wherever it's
defined per `measurement-ic-engine.md`) should be applied with peer group = {the variants
compared within that stratum} before `ops_ensemble_weight_compare.py` renders its verdict. At
minimum, if applying it pre-verdict is judged too invasive to the already-built script, record the
winner's IC as selection-biased in the decision log so nobody cites it as an unbiased estimate
later.

## Why this can't wait

Cheaper to do before the judgment runs than to unwind after — once a champion is promoted and
`alpha.ensemble.weight_method` is flipped based on an unshrunk winner's-curse-biased IC, undoing
that requires re-litigating a decision that's already shipped. The corpus rerun currently
in-flight (see todo 151) is the direct predecessor of this judgment — this fix should land before
that judgment is next attempted.
