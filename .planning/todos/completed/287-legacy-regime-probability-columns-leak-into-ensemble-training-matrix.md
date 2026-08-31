---
status: closed
closed: 2026-08-31
---

# 287 - Legacy `regime` family's probability/churn columns leak into `ensemble_trainer`'s training matrix

**Filed:** 2026-08-09
**Source:** Phase 172 plan 02, Task 2 (discovered while adding the parallel
`regime_volatility` exclusion, out of that task's own scope)
**Status:** **Fix landed 2026-08-12, committed 2026-08-13** (`9469b0a50`, confirmed via `git log`
2026-08-21 — this line previously said "uncommitted as of writing", stale) — see "Fix" section
below for what changed. **Impact assessment (sizing the correction, re-running `ensemble_trainer`)
still open** — do not close this todo until that's done. **Update 2026-08-13:** the corpus
pipeline run this was banking on to reach step 7 automatically FAILED at step 2 (disk-full
incident, see `project_disk_full_incident_2026_08_13` memory) — `ensemble_trainer` never ran.
This fix still needs its own explicit `ensemble_trainer` re-run once the pipeline is recovered;
don't assume it happened. **Update 2026-08-21: the corpus pipeline run currently in-flight
(`ops_corpus_pipeline_run.sh --from-step 5`, launched 2026-08-19) will reach step 7
(`ensemble_trainer`) once its `ic_engine`/step 5 finishes** — check `ensemble_weights`'s row
timestamps against this fix's landing commit once that step runs, rather than assuming a
separate dedicated re-run is still needed. Same run [285](285-phase172-full-scope-ic-engine-verification-after-volatility-cutover.md)/[335](335-regime-signal-bucket-tier-order-inversion-commodity-fx.md)/[306](306-corpus-pipeline-recovery-after-disk-full-incident.md)
are also gated on — check all four once it exits.

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

**Landed 2026-08-12, shape changed from the original proposal below (equivalent result, more
robust to future drift):** instead of hand-typing the 4 missing names, replaced the existing
hand-typed 4-name subset (`regime`/`hmm_regime_prob`/`hmm_entropy`/`hmm_duration`) with
`*REGIME_WRITER_OWNED_COLUMN_NAMES` (imported from `feature_vector_persistence.py`) — the same
single-source-of-truth pattern already used two lines below for the sibling
`REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES` family. This closes the exact class of bug this
todo describes permanently: the exclusion list and the Ring 1 ownership tuple can no longer
drift apart, because there is only one list now. Added regression test
`test_legacy_regime_family_fully_excluded_from_feature_matrix` in
`tests/unit/test_ensemble_trainer_meta_cols.py` (the pre-existing test file only stubbed the 4
already-protected columns, so it could not have caught this leak) — asserts the full 8-column
family via the same shared constant. 4/4 tests in that file pass; full `tests/unit/` suite green
(`tail -60` confirmed no failures); ruff/black clean.

Original proposal (superseded by the above, kept for the record):

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

## Closure (2026-08-31)

`ensemble_trainer` re-ran under the fix commit (`9469b0a50`, landed 2026-08-13) as part of
the post-Phase-173 corpus recompute: `ensemble_weights.computed_at` for
`weight_version='run_2025122405150000'` spans 2026-08-30 06:26:48-07:35:27, well after the
fix landed. Verified live, not assumed:

- **Zero leaked columns in the trained matrix**: `SELECT feature_name, count(*) FROM
  ensemble_weights WHERE feature_name IN ('hmm_prob_trending_up', 'hmm_prob_ranging',
  'hmm_prob_trending_down', 'hmm_churn', 'regime', 'hmm_regime_prob', 'hmm_entropy',
  'hmm_duration')` returns 0 rows -- the full 8-column `REGIME_WRITER_OWNED_COLUMN_NAMES`
  family is confirmed excluded from production training output, not just the unit test.
- **Impact assessment, sized**: `SELECT count(*) FILTER (WHERE hmm_prob_trending_up IS
  NULL), count(*) FILTER (WHERE hmm_churn IS NULL) FROM feature_vectors WHERE regime IS
  NOT NULL` returns 0/0 of 31,204,768 rows -- the NULL-imputation failure mode this todo
  described can no longer occur at all now that the columns are excluded outright,
  regardless of `regime_writer`'s partial-coverage population count.

Both of this todo's stated close conditions (re-run `ensemble_trainer`, size the
correction) are done.
