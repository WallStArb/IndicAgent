# 285 - Full-scope ic_engine verification after the Phase 172 volatility cutover

**Filed:** 2026-08-09
**Source:** Phase 172 cross-AI plan review (Codex, MEDIUM) incorporated into `172-07-PLAN.md`
**Status:** UNBLOCKED as of 2026-08-11 -- Phase 172 (volatility-only HMM redesign) is confirmed
EXECUTED and COMPLETE as of 2026-08-09 (`regime_volatility` column live via migration 307, see
[[project_hmm_regime_volatility_only_redesign_2026_08_08]] memory). The full-scope verification
this todo describes was never started -- Phase 172's own smoke test (172-07, four symbols at
1d) is the only validation that has run.

## What

Phase 172 repoints `ic_engine.py`'s per-symbol regime stratification from `feature_vectors.regime`
to `feature_vectors.regime_volatility`. Plan 172-07 validates that cutover with a scoped
`ic_engine.py --refresh` over four symbols at `1d`, explicitly labeled a smoke test. That run
proves the cutover produces volatility-keyed `feature_ic_scores` rows on the sampled cells. It does
not establish that every relabeled cell across the corpus produces correct IC output.

This todo tracks the full-scope verification that the smoke test deliberately does not perform.

## Why it is separate from Phase 172

A full `ic_engine` pass is the roughly 70-hour job STATE.md records. No gate inside Phase 172
depends on it: the phase's GO/NO-GO decision is plan 172-01's null-arm control, and the corpus
integrity properties are proven by plan 172-05's per-cell coverage accounting plus the post-relabel
provenance check. Folding a multi-day recompute into the phase would have made an already
long-chained phase longer without changing any decision it makes.

## What to do

Once Phase 172 is complete and no other corpus-scale job is running:

1. Run a full `ic_engine.py` pass (no `--symbols` / `--tf` scoping) with `--training-window-end`
   set per `docs/plans/OOS-EVAL-PROTOCOL.md`.
2. Confirm no row written under that `training_window_end` carries any of the retired trend labels
   `trending_up`, `trending_down`, `ranging`, `transition_up`, `transition_down` under
   `regime_scope = 'symbol_hmm'`.
3. Confirm every non-pooled `symbol_hmm`-scope row carries a code registered in
   `controlled_vocabulary` under namespace `regime_volatility`.
4. Compare the per-cell count of `symbol_hmm`-scope strata against
   `.planning/phases/172-hmm-regime-volatility-only-redesign/evidence/172-05-relabel-coverage.json`,
   and account for any cell the relabel recorded as `labeled` that produced no IC rows.
5. Re-run the `VINTAGE DISJOINT` intersection check from `172-IC-ENGINE-CUTOVER.md` against the
   grown table.

## Gotchas

- `ic_engine.py` uses a `ProcessPoolExecutor`. Killing the main process orphans workers still
  holding DB connections. Follow any kill with
  `ps aux | grep ic_engine.py | awk '{print $2}' | xargs kill` and confirm zero remain.
- Check for competing corpus-scale compute before launching.

## References

- `.planning/phases/172-hmm-regime-volatility-only-redesign/172-07-PLAN.md` Task 1
- `.planning/phases/172-hmm-regime-volatility-only-redesign/172-REVIEWS.md` (Codex, MEDIUM)
- `.planning/phases/172-hmm-regime-volatility-only-redesign/evidence/172-05-relabel-coverage.json`
