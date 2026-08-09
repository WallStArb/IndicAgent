---
phase: 172-hmm-regime-volatility-only-redesign
reviewed: 2026-08-09T20:54:46Z
depth: standard
files_reviewed: 17
files_reviewed_list:
  - docs/foundation/glossary.md
  - production/migrations/307_regime_volatility_schema_apr_cvr.sql
  - production/migrations/308_regime_volatility_apr_reconciliation.sql
  - production/migrations/309_feature_ic_scores_regime_vocabulary_comments.sql
  - scripts/ops/corpus/ops_regime_null_out_and_verify.py
  - services/ensemble_trainer.py
  - services/ic_engine.py
  - services/regime_writer.py
  - src/config/vocabulary_drift.py
  - src/intelligence/features/feature_vector_persistence.py
  - tests/unit/scripts/test_ops_regime_null_out_and_verify.py
  - tests/unit/services/test_ensemble_trainer_regime_source.py
  - tests/unit/services/test_ic_engine.py
  - tests/unit/services/test_regime_writer.py
  - tests/unit/test_ensemble_trainer_meta_cols.py
  - tests/unit/test_feature_vector_persistence_column_ownership.py
  - tests/unit/test_vocabulary_drift_audit.py
findings:
  critical: 0
  warning: 2
  info: 2
  total: 4
status: issues_found
---

# Phase 172: Code Review Report

**Reviewed:** 2026-08-09T20:54:46Z
**Depth:** standard
**Files Reviewed:** 17
**Status:** issues_found

## Summary

This phase generalizes `services/regime_writer.py`'s label-mapping / observation-matrix /
walk-forward machinery to a second column family (`regime_volatility`), cuts
`services/ic_engine.py`'s per-symbol stratification source over to it, and threads the
change through `ensemble_trainer.py`, `vocabulary_drift.py`,
`feature_vector_persistence.py`, and the ops null-out/verify tool. The diff is
unusually well self-documented (every non-obvious decision has an inline rationale
citing the research doc that grounds it) and has correspondingly deep test coverage —
row-order, vocab-swap, and reorder-inversion risks that would normally be silent are
each pinned by a dedicated "verified manually, goes red if reverted" test.

I traced the full write path end to end: `_build_obs_matrix_volatility` →
`_build_label_map`/`_state_groups_by_vocab` (vocab-parameterized) →
`_walk_forward_hmm_full` → `_compute_symbol_tf_volatility_walk_forward`'s tuple
assembly → `REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES`'s column order → the
`_bulk_update_by_key` SQL, and the `ic_engine.py` cutover (`_assert_prerequisites`,
the `fv_sql` SELECT, `_build_regime_passes`, `_resolve_regime_scope`). I did not find
any column-order, vocabulary, or SQL-injection defects — the `p_up`/`p_ranging`/
`p_down` → `hmm_vol_prob_turbulent`/`hmm_vol_prob_elevated`/`hmm_vol_prob_calm` reorder
that the code's own comments flag as "the single easiest thing here to get silently
wrong" is in fact correct, and matches its dedicated test.

The two findings below are both pre-existing correctness/quality concerns that this
phase's own `_walk_forward_hmm_full`/`_compute_hmm_churn` reuse strategy propagates
into a second write path (`hmm_vol_churn`) rather than something newly introduced by
this diff's own logic. I flag them as WARNING because the phase doubles their blast
radius (now two ML-training-relevant stat columns instead of one) even though neither
one is a regression this phase caused.

## Warnings

### WR-01: `hmm_churn`/`hmm_vol_churn` fabricate a spurious label-change event across a skipped walk-forward segment gap

**File:** `services/regime_writer.py:1102-1113` (trend path, pre-existing) and
`services/regime_writer.py:1259-1266` (volatility path, this phase's copy)

**Issue:** Both `_compute_symbol_tf_walk_forward` and its new
`_compute_symbol_tf_volatility_walk_forward` counterpart build the churn input by
concatenating only the *written* (non-degenerate) segments' label lists, in segment
order:

```python
all_written_labels: list[str] = []
for seg in segment_results:
    if not seg["is_degenerate"]:
        all_written_labels.extend(seg["labels"])
churn_values = _compute_hmm_churn(all_written_labels, churn_window)
```

`_compute_hmm_churn` (line 598) computes `changes[i] = labels[i] != labels[i-1]` over
this concatenated array with no knowledge of which adjacent pairs actually came from
temporally adjacent bars. When a degenerate/non-converged segment is skipped between
two written segments, the label at the end of the written segment before the gap and
the label at the start of the written segment after the gap become direct neighbors in
`all_written_labels`, even though real time (potentially a large multi-year window,
since walk-forward warmup/refit windows run into the thousands of bars) elapsed
between them with no observation at all. If those two labels differ (a very likely
outcome for two independently-drawn segments), `_compute_hmm_churn` records a "label
change" at that boundary and the resulting elevated churn rate propagates into
`hmm_churn`/`hmm_vol_churn` for up to `churn_window` bars after the gap — a fabricated
regime-transition signal at a boundary where no transition was actually observed.

The volatility path's own docstring comment (lines 1259-1261, copied near-verbatim
from the trend path) asserts this is safe: "Those gaps are exactly where
duration/prev_label also reset below, so churn's own 'first bar after a gap has no
real predecessor' edge case lines up with the same discontinuity duration already
treats specially." This claim does not hold: `duration`/`prev_label` are reset
*before* the loop that builds `update_rows` (correctly severing continuity for that
column), but `churn_values` is precomputed once on the already-concatenated
`all_written_labels` *before* any reset logic runs, so churn's per-bar values are never
actually reset at the gap the way duration's are. The comment describes an invariant
the code does not implement.

**Fix:** Compute churn per contiguous written segment (or per run of consecutive
non-degenerate segments), resetting the "no predecessor" case at each gap boundary,
e.g.:

```python
churn_values = np.concatenate([
    _compute_hmm_churn(seg["labels"], churn_window)
    for seg in segment_results if not seg["is_degenerate"]
]) if any_written else np.zeros(0)
```

This makes the first bar of every post-gap segment define `changes[0] = 0` (no real
predecessor) instead of comparing against the last label of a temporally distant
segment. Apply the same fix to both `_compute_symbol_tf_walk_forward` (trend) and
`_compute_symbol_tf_volatility_walk_forward` (volatility) since both share the bug.

---

### WR-02: `_hmm_seed_stability_check`'s `covariance_type` retry parity is not carried over to the volatility path's stability diagnostics story

**File:** `services/regime_writer.py:1335-1400`

**Issue:** Minor, pre-existing quality note surfaced while tracing the volatility
path's dependencies: `_hmm_seed_stability_check` (the todo 026 multi-seed diagnostic)
calls `_build_label_map(model.means_)` with no `vocab` argument (line 1379), so it is
permanently hardwired to `_TREND_VOCAB` even though the function is otherwise generic
over `obs_matrix`/`n_components`/`covariance_type` and could equally be pointed at a
volatility-axis `obs_matrix`. This isn't a correctness bug for the current phase (the
function isn't called anywhere in the new volatility write path — verified via grep,
only referenced by its own tests and a docstring), but if a future operator ever wants
to run the same multi-seed stability diagnostic against `regime_volatility` fits (a
reasonable ask given migration 308's window reconciliation was itself justified by a
similar kind of sweep), the function will silently mislabel the diagnostic's output
with trend vocabulary (`trending_up`/`ranging`/`trending_down`) for what is actually a
volatility fit, rather than raising or accepting a `vocab` passthrough.

**Fix:** Thread an optional `vocab: dict[str, str] | None = None` parameter through to
the internal `_build_label_map` call, mirroring the pattern already used by
`_walk_forward_hmm_full`, so a future volatility-path caller doesn't get
silently-wrong labels:

```python
def _hmm_seed_stability_check(
    obs_matrix: np.ndarray,
    n_components: int,
    covariance_type: str,
    n_iter: int,
    seeds: list[int],
    full_cov_min_obs: int,
    vocab: dict[str, str] | None = None,
) -> dict:
    ...
    label_map = _build_label_map(model.means_, vocab=vocab)
```

## Info

### IN-01: `ops_regime_null_out_and_verify.py`'s dry-run summary count is dead/always-zero (pre-existing, unaffected by this phase)

**File:** `scripts/ops/corpus/ops_regime_null_out_and_verify.py:327,368-372`

**Issue:** `n_dry_run_updates` is initialized to `0` and never incremented anywhere in
`_run_null_out`, so the printed `"DRY-RUN SUMMARY: ... {n_dry_run_updates} UPDATE
statement(s) issued"` always reports `0`. This happens to be numerically correct
(dry-run never issues an UPDATE) but the variable is dead weight that reads as if it
were meant to track something. Pre-existing before this phase (not part of the plan
172-05 generalization diff) — noted only because the surrounding function was touched
by this phase's `--column-family` generalization and would be a natural place to clean
up in a future pass.

**Fix:** Remove the unused variable and hardcode `0` in the f-string, or delete the
line entirely since it adds no information beyond "dry-run, so zero."

### IN-02: `_write_regime_volatility_results` duplicates ~35 lines of `_write_regime_results` verbatim aside from the column family and log-event names

**File:** `services/regime_writer.py:1803-1950`

**Issue:** `_write_regime_results` and `_write_regime_volatility_results` are
structurally identical (bulk update → commit → paired NOT NULL/NULL count query →
gauge set → log → return) with only the target column, gauge label, and log-event
name differing. This is likely already covered by the phase's own filed follow-up
todos (290/291) for deferred structural duplication per the review scope note, but
flagging explicitly in case it wasn't captured: a future third column family (or a bug
fix to the shared shape, e.g. WR-01 above if teams choose to add gap-aware logging
here too) requires editing both functions in lockstep with no structural guard against
drift, unlike the column-name lists which do have that guard via
`REGIME_WRITER_OWNED_COLUMN_NAMES`/`REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES`.

**Fix:** If not already tracked by todo 290/291, extract a shared
`_write_regime_family_results(conn, symbol, tf, update_rows, converged, tracer, *,
label_col, gauge, log_event_prefix, heldout_ll=None)` helper parameterized on the
column-family specifics, called by two thin wrappers.

---

_Reviewed: 2026-08-09T20:54:46Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
