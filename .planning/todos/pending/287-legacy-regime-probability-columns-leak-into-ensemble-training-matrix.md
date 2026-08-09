# 287 - Legacy `regime` family's probability/churn columns leak into `ensemble_trainer`'s training matrix

**Filed:** 2026-08-09
**Source:** Phase 172 plan 02, Task 2 (discovered while adding the parallel
`regime_volatility` exclusion, out of that task's own scope)
**Status:** pending, not blocking

## The bug

`src/intelligence/features/feature_vector_persistence.py::REGIME_WRITER_OWNED_COLUMN_NAMES`
(the legacy `regime` family) has 8 members:

```
regime, hmm_prob_trending_up, hmm_prob_ranging, hmm_prob_trending_down,
hmm_regime_prob, hmm_entropy, hmm_duration, hmm_churn
```

`services/ensemble_trainer.py::_get_feature_columns`'s `_META_COLS` frozenset excludes only 3 of
these 8 from the training feature matrix: `regime`, `hmm_regime_prob`, `hmm_entropy`,
`hmm_duration` (plus `regime_label_source`, PK/metadata columns). It does NOT exclude
`hmm_prob_trending_up`, `hmm_prob_ranging`, `hmm_prob_trending_down`, or `hmm_churn`.

Coverage for the whole `REGIME_WRITER_OWNED_COLUMN_NAMES` family is inherently partial —
`regime_writer.py`'s `UPDATE ... WHERE regime IS NULL` pass does not label every bar (warmup
prefix bars, degenerate segments). The same "a NULL here is not 'no signal'" reasoning that
justifies excluding `hmm_regime_prob`/`hmm_entropy`/`hmm_duration` applies identically to
`hmm_prob_trending_up`/`hmm_prob_ranging`/`hmm_prob_trending_down`/`hmm_churn` — they are written
by the exact same partial-coverage UPDATE pass, at the exact same rows. Today, any row where
`regime_writer.py` has not yet labeled a bar has `hmm_prob_trending_up` etc. as NULL, and
`ensemble_trainer`'s downstream matrix-construction step silently imputes that NULL to a
fabricated `0.0` — indistinguishable from "trend probability measured as exactly zero," which is
never true for a real HMM posterior.

## Why it was not fixed as part of Phase 172 plan 02

Phase 172 plan 02's Task 2 added the parallel `regime_volatility` family's exclusion
(`REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES`, all 8 members correctly excluded from
`_META_COLS`) and discovered this pre-existing asymmetry in the legacy family while reading
`_get_feature_columns` as the analog to copy. Fixing the legacy gap is out of scope for that
task — it is a correctness bug in code Phase 172 does not otherwise touch, not something the new
column family's plan should silently bundle a fix for. Filed here instead, per plan's explicit
instruction not to change legacy behavior in-plan.

## Fix

Add the 4 missing names to `services/ensemble_trainer.py::_get_feature_columns`'s `_META_COLS`:

```python
"hmm_prob_trending_up",
"hmm_prob_ranging",
"hmm_prob_trending_down",
"hmm_churn",
```

with a comment matching the existing `hmm_regime_prob`/`hmm_entropy`/`hmm_duration` rationale.

## Impact assessment (do before or alongside the fix)

This is a live measurement-integrity gap, not just a latent one — unlike todo 286's warmup-prefix
artifact, `regime_writer.py`'s partial coverage is ongoing (any (symbol, tf) not yet reached by a
labeling pass, or any bar predating the walk-forward warmup window) and every `ensemble_trainer`
run since the legacy family started being populated has trained on `0.0`-imputed
trend-probability/churn values for those rows. Before shipping the fix:

1. Query how many currently-eligible training rows (`feature_ic_scores` eligibility criteria,
   see `ensemble_trainer.py::_eligibility_where`) have NULL `hmm_prob_trending_up` (or siblings)
   today, to size the correction.
2. Landing the fix changes `ensemble_weights`/`ensemble_alpha` outputs for any stratum that used
   these columns with nonzero weight — treat like any other `ensemble_trainer` methodology
   change (re-run required, not a silent hotfix).

## References

- `.planning/phases/172-hmm-regime-volatility-only-redesign/172-02-PLAN.md` Task 2
- `src/intelligence/features/feature_vector_persistence.py::REGIME_WRITER_OWNED_COLUMN_NAMES`
- `services/ensemble_trainer.py::_get_feature_columns`, `_META_COLS`
