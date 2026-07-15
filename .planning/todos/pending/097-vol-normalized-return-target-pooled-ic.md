# 097 — Vol-normalized return target for POOLED-strata IC (split from todo 077's L3-1)

**Status check 2026-07-14 (corpus-rebuild idle window):** the implementation half is done —
`_cross_sectional_vol_normalized_target` (Component F) is live in `ic_engine.py`, with
`scripts/ops/alpha/ops_vol_normalized_target_ab.py` as the A/B comparison harness. **Not closing
this todo** — the actual deliverable is the "Validation design" section below (compare
qualifying-feature rankings raw-vs-vol-normalized, decide keep-or-retire), which hasn't run yet
and can't until Phase 143.1-07's corpus re-run completes (same corpus this A/B rides, per "Why
this rides Phase 143.1" below). Code existing is not the same as the question being answered.

**Split 2026-07-11:** todo 077 bundled three outcome-target refinements (L3-1, L3-2, L3-4) with
different gates. L3-1 is unblocked today and directly sharpens the exact `ic_ci_lower`/
`ic_ci_upper` mechanism Phase 143.1 is already correcting (Fisher-z CI, sign-symmetric
eligibility) in the same corpus re-run — same reasoning that keeps 077's L3-2 (gated on Phase
145's betas) and L3-4 (diagnostic-only) deferred as-is. Folded into Phase 143.1 as Component F;
see `.planning/todos/deferred/077-outcome-target-refinements-vol-normalized-residual-overnight.md`
for L3-2/L3-4, which remain separately deferred.

**Source:** `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §6 (L3-1).
**Priority:** P1 — high value, cheap, unblocked today, no schema dependency.
**Gate:** none. Zero new parameters beyond an existing feature's window; a join + divide inside
`ic_engine`'s existing corpus load.

## The problem

`return_x / trailing_sigma(symbol)` (sigma from the existing `atr_z` denominator or a trailing
realized vol) as an alternative return target. The payoff is cross-sectional/POOLED measurement:
raw-return ranks are dominated by whichever symbols happen to be running hot on a given bar, and
the ensemble trains exclusively on POOLED strata (`ensemble_trainer.py:317,430,469,540`) — so the
pooled IC the whole system keys on is currently vol-biased.

## Validation design (do not silently swap the target)

Re-run POOLED strata with **both** targets (raw and vol-normalized) and compare qualifying-
feature rankings directly. If rankings are materially identical, the transform is unnecessary —
retire it, don't force it in. This A/B is deliberate: Phase 143.1 already bundles a Fisher-z CI
fix (Component A) and a sign-symmetric eligibility redesign (Component E) into the same corpus
re-run, and adding this as a third simultaneous change to the same `ic_ci_lower`/`ic_ci_upper`
numbers would confound attribution if swapped in silently. Running it as an explicit before/after
comparison (not a blind replacement) keeps each of the three changes separately diagnosable.

## Why this rides Phase 143.1 rather than waiting for the v3.15/Phase 151 batch

Components A and E both already require a full `ic_engine` corpus re-run — this transform reads
from the exact same corpus load, at zero incremental schema/DAG cost, so bundling it in spends
that re-run once rather than burning a second cycle for a change that's ready today. Contrast
with todo 073 (cross-sectional relative-value feature family) and todo 077's L3-2/L3-4, which
need new schema/DAG steps or a separate phase's outputs (Phase 146's betas) and correctly stay in
the larger v3.15/Phase 151 batch instead.
