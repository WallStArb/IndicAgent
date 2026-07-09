# 069 - Winner's-curse correction before the E1/E2 champion judgment (COMPLETE - judgment ran, E2 rejected)

**Source:** `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §7 (L4-3),
concretizes `docs/research/measurement-ic-engine.md` Open Question 7.
**Priority:** LOW - the code fix that had to land before the judgment is now landed. What
remains is a one-time operational step (OOS confirmation) that only applies once the judgment
actually runs and promotes a champion.
**Gate:** none.

**Status (2026-07-09): peer-group question ANSWERED, implementation LANDED.** The decision
doc (`docs/research/fable-2026-07-09-ensemble-winners-curse-peer-group.md`) concluded there is
NO defensible shrinkage peer group at ensemble-variant grain - `shrink_ic()` is not applied to
variant ICs at all. The comparison is a pairwise CI-ordering test per stratum, not a k-way
argmax; the real residual biases are (a) across-strata multiplicity, (b) post-selection
reporting of the winner's point IC, and (c) sequential-ladder multiplicity across rounds.

## Implementation (complete, 2026-07-09)

1. ✅ `src/intelligence/statistics/ic_math.py`: `fisher_z_difference_p()` pure kernel helper
   added - two-sided p-value for the difference between two IC estimates via Fisher z,
   conservative under positive dependence (same-corpus measurement), NaN on degenerate n.
2. ✅ `scripts/ops/alpha/ops_ensemble_weight_compare.py`: `_COMPARE_SQL` now selects
   `ic_value`/`n_independent`; per-stratum difference p computed for every stratum, ONE
   `multipletests` BH-FDR pass across all strata in the run
   (`alpha.ensemble.compare_fdr_alpha`, migration 213, seeded 0.05 - applied to the live DB);
   verdict is now `_final_verdict(win, bh_reject)`: WIN requires D-10 AND BH survival,
   `WIN-FDR-VETO` for D-10-pass/BH-fail (distinct from LOSS, not silently folded in);
   `_D15_WINNERS_CURSE_CAVEAT` text rewritten to state the citation rule (cite `ic_ci_lower`,
   not `ic_value`) and point at the decision doc instead of the stale "todo 153"; footer
   states the full reporting rule.
3. ✅ `tests/unit/test_ensemble_weight_compare.py`: extended - `_final_verdict` truth table
   (LOSS regardless of BH, WIN on BH-reject, WIN-FDR-VETO on BH-fail, HOLD on degenerate p),
   BH veto of a lone marginal WIN among ~40 null strata, BH pass on a genuine multi-stratum
   WIN, `_COMPARE_SQL` selects the new columns. `tests/unit/test_ensemble_ic_math.py`:
   `fisher_z_difference_p` - identical ICs, large/small gaps, symmetry, degenerate n, unit
   interval. 27/27 new+existing tests green; ruff/black clean.
4. ✅ `docs/plans/methodology-change-ledger.md`: E5 entry added, pre-registered (written
   before the judgment has ever run - the clean E4 pattern).

## Judgment result (2026-07-09)

Ran `ops_ensemble_weight_compare.py --champion run_2025122405150000 --challenger
run_2025122405150000_mv` (E1 = shrunk-IC, E2 = mean-variance Σ⁻¹·IC) against the fresh,
trustworthy corpus (6th rebuild, completed 08:44 same day). Result: **E2 LOSS in all 20/20
strata** (5m/15m/1d × regime) - no WIN, no WIN-FDR-VETO. E1 remains champion by default
everywhere; nothing was promoted.

Item 5 (OOS confirmation) does not apply - it only triggers on a promotion, and this judgment
produced none. Nothing left on this todo.

## Why this could wait no longer

The corpus rebuild (todo 067, the judgment's direct predecessor) completed end-to-end
2026-07-09 - the E1/E2 judgment is now the next real step on the critical path. This fix
needed to land before that judgment runs, not after: undoing a champion promoted off an
uncorrected verdict means re-litigating a shipped decision. It has landed. The judgment can
now be run.
