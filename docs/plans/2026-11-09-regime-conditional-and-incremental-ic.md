# Regime-conditional and incremental IC: the discovery sweep's levels 2 and 3

**Status:** Plan, 2026-11-09. Not built. Executes under todo 601 after the data gate; no real-data run before the owner's clean-data rule lifts.
**Author:** Claude session 1fb77ae9, 2026-11-09, at the owner's direction ("discovery, not deletion").
**Informed by:** `src/intelligence/measure/` (`ic.py`, `proposer.py`, `regime_disclosure.py`), `src/intelligence/research/combiner.py` and `contribution.py`, `services/ic_measure.py::feature_names`, `docs/plans/2026-09-24-evidence-framework.md` (E15-E18), glossary entries `family`, `predictor`, `feature group`.

## Why

A feature that belongs to no family can carry signal in three ways. Level 1 (pooled IC per feature, timeframe and horizon, BH-FDR across the block) exists and already covers every numeric column of `feature_vectors`. Levels 2 and 3 do not:

- Level 2, regime-conditional IC: `regime_disclosure.py` computes one stratified IC, for `regime_volatility`, disclosure only. A pooled IC near zero can hide a strong IC of opposite sign in two regimes.
- Level 3, incremental IC: nothing screens a candidate against existing members. `contribution.py` explains members already in a book and is diagnostics only.

## Level 2: one generic stratified kernel

`regime_volatility_disclosure` already does the work for one label array. Generalize, do not duplicate:

```
stratified_ic(features, feature_names, stack, labels, params, *, present, complete=None)
    -> dict[str, IcCell]          # one pooled cell per regime state, same IcCell as level 1
```

- `labels` is any [n, m] state array from a regime group that exists (see the review note below). Missing labels drop the row (no fill).
- `regime_volatility_disclosure` becomes a thin call into `stratified_ic`. Its output must stay bit-identical; keep the existing tests as the check. (`measure/` is not under the frozen-verdicts rule, which covers `research/` and `statistics/`; run `repro_frozen` only if those change.)
- Pure numpy, no I/O. Row masks reuse `label_row_masks`. States with fewer than `params.min_obs` strided pairs are unreliable cells, as in level 1.
- Regime columns before the walk-forward rebuild are refused (todo 248, `refuse_regime_columns`); a stratified run reads rebuilt labels only. Review 2026-11-09: the regimes that exist are `regime` and `regime_volatility` in `feature_vectors` (per symbol) and the `market_regimes` groups (commodity, equity, fx, rates; market-wide, so a label must broadcast to [n, m]). The quadrant and fragile-divergence states are designs in `docs/ideas/signal-scoped-regime-states.md`, not code. `refuse_regime_columns` lives in `research/feature_inputs.py` and `ic_measure` does not call it; a stratified run must.

Design amendment needed first: unified design section 11 keeps regime-stratified IC "as disclosure for `regime_volatility` only". Stratifying by other regime groups reverses that, so add a design amendment and a methodology ledger entry before building.

## Level 3: partial IC against family members

```
incremental_ic(features, feature_names, stack, member_alphas, params, *, present)
    -> IcCell                      # IC of each candidate after removing the member span per cell
```

`member_alphas` is the factor-residualized stack [t, i, k] the S7 combiner already consumes. For each date cell, regress the candidate's cross-sectional rank on the members' ranks and score the residual against the target, pooled with the same stride rule. A candidate correlated with a member scores near zero whatever its own IC. Review 2026-11-09: member alphas exist only inside a runner run of one book spec and are factor-residualized against the S1 residual target (`research/combiner.py`), while level 1 scores raw executable returns. So level 3 is a runner evidence job per pre-registered family, on the S1 target with the candidate residualized by the same causal factors; `ic_measure` keeps only levels 1 and 2. The kernel stays pure and lives with the other research kernels; reuse `research/contribution.py`'s `uniqueness`, `effective_breadth` and `correlation_clusters` instead of writing new ones.

## Look count, declared before any run

```
n_looks = n_features x n_states_total x n_timeframes x n_horizons          # level 2
  + n_features x n_timeframes x n_horizons                           # level 3
```

Level 1 adds `n_features x n_timeframes x n_horizons`. The run records `n_looks` in its ledger row before computing. Selection across all levels is StepM over the full `n_looks`, not per level; the existing BH-FDR across the block stays the proposer's display statistic only. Interactions between feature pairs are out of scope here: they are tested only for candidates that pass a level or carry a pre-registered mechanism (todo 601).

## Tests

- `stratified_ic` on a planted case: two states with equal and opposite true IC gives pooled IC near zero and per-state ICs of opposite sign.
- `regime_volatility_disclosure` bit-identical before and after the refactor (existing tests plus `repro_frozen`).
- `incremental_ic`: a candidate that is an exact copy of a member scores NaN or zero; an independent signal keeps its IC; a candidate equal to member plus independent noise keeps only the noise's IC.
- Determinism: same inputs, same bytes; permuting symbol order changes nothing.

## Order of work

1. Level 2 kernel and refactor, tests, `repro_frozen`.
2. Level 3 kernel and tests.
3. Wire level 2 into `ic_measure`; wire level 3 as a runner evidence job per family. Both record `n_looks` before measuring.
4. First real-data run only when the data gate passes and the owner lifts the clean-data rule.

## Gates

`/simplify`, `/review`, `pytest tests/unit/ -n auto`, `repro_frozen` bit-identical for any edit under `research/` or `statistics/` (level 3 touches `research/`). No edit to a module a live fingerprinted batch writer imports while its run is live.
