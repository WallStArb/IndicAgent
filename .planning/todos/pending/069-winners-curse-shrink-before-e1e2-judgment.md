# 069 - Winner's-curse correction before the E1/E2 champion judgment (peer-group decision MADE; implementation open)

**Source:** `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §7 (L4-3),
concretizes `docs/research/measurement-ic-engine.md` Open Question 7.
**Priority:** MEDIUM - decision made 2026-07-09; remaining work is a small, well-specified
implementation that must land before the E1/E2 judgment is next attempted.
**Gate:** none. The design decision this todo was blocked on is resolved:
`docs/research/fable-2026-07-09-ensemble-winners-curse-peer-group.md`.

**Status (2026-07-09): peer-group question ANSWERED, implementation still open.** The decision
doc concludes there is NO defensible shrinkage peer group at ensemble-variant grain -
`shrink_ic()` is not applied to variant ICs at all. The comparison is a pairwise CI-ordering
test per stratum (already ~p<0.006 stringent), not a k-way argmax; the real residual biases are
(a) across-strata multiplicity, (b) post-selection reporting of the winner's point IC, and
(c) sequential-ladder multiplicity across rounds. The corrections are BH-FDR across strata in
the compare script, `ic_ci_lower` + OOS holdout as the citable number, and
methodology-change-ledger entries per round. Full reasoning and rejected alternatives (LOO
across variants, cross-strata prior, hierarchical two-level, conditional post-selection
inference) in the decision doc §4.

## Remaining implementation (per decision doc §6 - write the plan from there)

1. `src/intelligence/statistics/ic_math.py`: add pure `fisher_z_difference_p()` kernel helper.
2. `scripts/ops/alpha/ops_ensemble_weight_compare.py`: `_COMPARE_SQL` selects
   `ic_value`/`n_independent`; per-stratum difference p + BH across strata; WIN requires D-10
   AND BH survival (`WIN-FDR-VETO` verdict for D-10-pass/BH-fail); new APR key
   `alpha.ensemble.compare_fdr_alpha` (seeded `[conventional]`); update
   `_D15_WINNERS_CURSE_CAVEAT` text (point at decision doc; fix stale "todo 153" → 069);
   footer states the reporting rule.
3. `tests/unit/test_ensemble_weight_compare.py`: extend (BH veto of lone marginal WIN,
   multi-stratum pass, degenerate n).
4. `docs/plans/methodology-change-ledger.md`: entry in the implementing commit (this is a
   pre-registered rule change - judgment has never run).
5. OOS confirmation step for any promoted champion via `ensemble_ic_engine.py` over the holdout
   per `docs/plans/OOS-EVAL-PROTOCOL.md` before its IC is cited anywhere downstream.

## Why this can't wait

Unchanged: cheaper to land before the judgment runs than to unwind after - once a champion is
promoted and `alpha.ensemble.weight_method` flips on an uncorrected verdict, undoing it means
re-litigating a shipped decision. The corpus rerun (todo 067) is the direct predecessor of the
judgment; this implementation should land before that judgment is next attempted. The interim
D-15 caveat (commit `ac9e7f25`) remains in place until then, so no verdict can be silently
misread in the meantime.
