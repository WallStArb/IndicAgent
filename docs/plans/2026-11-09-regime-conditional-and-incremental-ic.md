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

- `labels` is any [n, m] state array from a stored regime group (quadrant, rates curve, HMM groups, volatility). Missing labels drop the row (no fill).
- `regime_volatility_disclosure` becomes a thin call into `stratified_ic`. Its output must stay bit-identical: it is under the frozen-verdicts rule, so run `repro_frozen` before and after.
- Pure numpy, no I/O. Row masks reuse `label_row_masks`. States with fewer than `params.min_obs` strided pairs are unreliable cells, as in level 1.
- Regime columns before the walk-forward rebuild are refused (todo 248, `refuse_regime_columns`); a stratified run reads rebuilt labels only.

## Level 3: partial IC against family members

```
incremental_ic(features, feature_names, stack, member_alphas, params, *, present)
    -> IcCell                      # IC of each candidate after removing the member span per cell
```

`member_alphas` is the factor-residualized stack [t, i, k] the S7 combiner already consumes. For each date cell, regress the candidate's cross-sectional rank on the members' ranks and score the residual against the target, pooled with the same stride rule. A candidate correlated with a member scores near zero whatever its own IC. Pure kernel in `measure/`, called by the runner; `contribution.py` stays post-hoc.

## Look count, declared before any run

```
L = n_features x n_states_total x n_timeframes x n_horizons          # level 2
  + n_features x n_timeframes x n_horizons                           # level 3
```

Level 1 adds `n_features x n_timeframes x n_horizons`. The run records `L` in its ledger row before computing. Selection across all levels is StepM over the full `L`, not per level; the existing BH-FDR across the block stays the proposer's display statistic only. Interactions between feature pairs are out of scope here: they are tested only for candidates that pass a level or carry a pre-registered mechanism (todo 601).

## Tests

- `stratified_ic` on a planted case: two states with equal and opposite true IC gives pooled IC near zero and per-state ICs of opposite sign.
- `regime_volatility_disclosure` bit-identical before and after the refactor (existing tests plus `repro_frozen`).
- `incremental_ic`: a candidate that is an exact copy of a member scores NaN or zero; an independent signal keeps its IC; a candidate equal to member plus independent noise keeps only the noise's IC.
- Determinism: same inputs, same bytes; permuting symbol order changes nothing.

## Order of work

1. Level 2 kernel and refactor, tests, `repro_frozen`.
2. Level 3 kernel and tests.
3. Wire both into the `ic_measure` proposer job behind the declared-`L` ledger row.
4. First real-data run only when the data gate passes and the owner lifts the clean-data rule.

## Gates

`/simplify`, `/review`, `pytest tests/unit/ -n auto`, `repro_frozen` bit-identical for any edit under `research/` or `statistics/`. No edit to a module a live fingerprinted batch writer imports while its run is live.
