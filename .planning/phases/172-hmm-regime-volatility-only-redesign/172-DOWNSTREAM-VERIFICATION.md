# Phase 172 Plan 07 -- Downstream Re-Verification

Records both halves of plan 172-07's downstream re-verification of the `regime_volatility`
cutover: whether `ensemble_trainer.py` needed a repoint (it did not, proven by regression
test), and what a real scoped `ic_engine.py --refresh` run actually wrote.

## ensemble_trainer stratum source

**Conclusion: `ensemble_trainer.py` requires no repoint and none was made.** Its stratum
source is cross-sectional POOLED IC in `feature_ic_scores`, not the per-symbol
`feature_vectors.regime` / `feature_vectors.regime_volatility` column plan 172-06 changed.

`services/ensemble_trainer.py`'s `_eligibility_where()` builds the filter every consumer in
the file shares:

```sql
symbol = 'POOLED' AND is_pooled = true AND regime != '_pooled'
  AND {significance_clause} AND reliable = true AND ic_sharpe_hac IS NOT NULL
  AND passes_walkforward = true
```

The strata-discovery query (`_execute_inner`, around line 748) reads:

```sql
SELECT DISTINCT tf, regime
FROM feature_ic_scores
WHERE {eligibility_where}
  AND regime IS NOT NULL
ORDER BY tf, regime
```

Both queries read exclusively from `feature_ic_scores`, filtered to `symbol = 'POOLED'`
rows -- the cross-sectional pass `ic_engine.py` writes per `(regime_group, tf, market_regimes
label)`, stamped `regime_scope = 'cross_sectional'`. Neither query references
`feature_vectors`, `regime_volatility`, or `regime_scope = 'symbol_hmm'` anywhere. Per-stratum
processing (`_process_stratum`) does fetch a feature matrix from `feature_vectors`, but joins
it to `market_regimes` on `(regime_group='equity', tf, ts=bar_ts)` and filters on
`mr.regime_label` -- the cross-sectional label -- never on `fv.regime` or
`fv.regime_volatility`. In every query and every branch, `regime` is threaded through purely
as an opaque bound SQL parameter (`tf = $1 AND regime = $2`) and an opaque dict/tuple value
(the `ensemble_weights` and `ensemble_alpha` INSERT rows both carry `regime` unmodified);
nothing in `_process_stratum`'s ~350 lines branches on the label string itself, in either the
retired trend vocabulary (`trending_up`/`trending_down`/`ranging`/`transition_up`/
`transition_down`) or the live volatility vocabulary (`calm`/`elevated`/`turbulent`).

This means `ensemble_trainer.py` was already correct before plan 172-06 shipped and remains
correct after it: it consumes whatever vocabulary `ic_engine.py`'s cross-sectional pass
happens to write to `feature_ic_scores.regime` under `regime_scope = 'cross_sectional'`, a
column this phase's cutover never touches. Plan 172-02 already added the eight new
`regime_volatility`-family columns to `ensemble_trainer.py`'s `_META_COLS` exclusion set (so
they never leak into the numeric feature matrix as fake floats) -- the only change this module
needed for the whole phase.

**Regression coverage:** `tests/unit/services/test_ensemble_trainer_regime_source.py` (new
file, 9 tests, all passing) pins this independence by test rather than by argument:

- `test_eligibility_where_base_contains_required_clauses` / `..._full_adds_passes_fdr...` --
  call the real `_eligibility_where()` and assert on its live return value.
- `test_strata_discovery_query_selects_distinct_tf_regime_from_feature_ic_scores` /
  `..._does_not_reference_feature_vectors_or_regime_volatility` -- source-inspection
  (`inspect.getsource` + regex) on the actual strata-discovery SQL block.
- `test_process_stratum_never_special_cases_any_regime_label_string` /
  `test_process_stratum_ic_rows_query_binds_regime_as_parameter` /
  `test_fv_join_query_does_not_select_or_filter_on_feature_vectors_regime_column` --
  source-inspection on `_process_stratum`, covering both vocabularies and the
  `feature_vectors`/`market_regimes` join.
- `test_calm_stratum_processed_identically_to_cross_sectional_stratum` --
  **behavioral**, not just source-level: drives the real `_process_stratum()` end-to-end
  twice with byte-identical synthetic IC/feature data, varying only the regime label
  (`'trending_up'` vs `'calm'`), and asserts the resulting `ensemble_weights` and
  `ensemble_alpha` INSERT rows are identical except for the regime field itself.
- `test_volatility_label_iterated_as_ordinary_stratum_no_exception` -- confirms a volatility
  label runs the full stratum-processing path without error or divergence.

Verified during authoring per the plan's acceptance criteria: temporarily removing the
`regime != '_pooled'` clause from `_eligibility_where()`'s `base_where` string and re-running
`test_eligibility_where_base_contains_required_clauses` produced a failure (`AssertionError:
assert "regime != '_pooled'" in "symbol = 'POOLED' AND is_pooled = true AND ic_ci_lower > 0
AND reliable = true AND ic_sharpe_hac IS NOT NULL AND passes_walkforward = true"`); restoring
the clause restored green. `git status --short services/ensemble_trainer.py` shows no
modification from this task -- the mutation was applied, verified, and reverted within the
same tool-call sequence, never committed.

## Scoped ic_engine refresh

This was a four-cell (later widened to five, see below) smoke test, not a full-corpus
recompute: it proves the `regime_volatility` cutover produces volatility-keyed
`feature_ic_scores` rows on the sampled cells, and it does not establish that every relabeled
cell in the 80-symbol/4-timeframe corpus produces correct IC output. Full-scope verification
is tracked as pending todo 285
(`.planning/todos/pending/285-phase172-full-scope-ic-engine-verification-after-volatility-cutover.md`)
and is deliberately out of scope here.

**Scope:** `SPY`, `QQQ`, `IWM`, `GLD` at `1d`, `--training-window-end 2025-12-24T05:15:00Z`
(the OOS holdout clamp, `alpha.validation.oos_start`), `--refresh`. All four cells have
`verdict = 'labeled'` in `evidence/172-05-relabel-coverage.json`. All 80 symbols in this
Phase A ETF corpus carry `instruments.contract_details->>'asset_class' = 'equity'` (confirmed
by direct query) -- the plan's 3-distinct-asset-class target is unreachable from this corpus
at any timeframe; GLD (commodity-backed) was chosen as the closest available proxy to a
distinct return-driver profile.

**Before/after:** `feature_ic_scores` row count 1,062,880 -> 1,091,788 (+28,908).
`regime_scope` breakdown before: `cross_sectional=630720, symbol_hmm=338720, pooled=93440`.

**Finding, not a pass, on the primary 4-symbol scope:** zero `symbol_hmm`-scope rows were
committed for SPY/QQQ/IWM/GLD at `1d`, despite per-symbol clustering visibly running against
all three volatility regimes for each symbol (see `logs/172-07-ic-refresh-scoped.log`,
`event=ic_engine.clustering`). Diagnosed mechanically, not attributed to a cutover-code
defect: `alpha.ic.min_reliable_n=100` and `alpha.ic.subsample_min_stride=5` together require
roughly 500+ raw regime-labeled rows in a cell before `n_independent = raw_rows / stride`
clears the reliability floor. Every one of the four symbols' three regime buckets, measured
directly within the training window, fell short (SPY calm=177/elevated=18/turbulent=57; QQQ
calm=135/elevated=128/turbulent=365; IWM calm=178/elevated=110/turbulent=216; GLD
calm=400/elevated=176/turbulent=49). This is a property of `1d`'s currently-thin
`regime_volatility` coverage (a few hundred rows per symbol, not the full multi-year history)
intersected with a pre-existing, phase-172-unrelated reliability gate -- confirmed by checking
`forward_returns` coverage (complete for all three buckets) and the fingerprint bypass (dry-run
partition showed all 4 symbols correctly marked `compute`, not `skip`) before landing on the
stride/min_reliable_n explanation.

**Supplementary symbol added to produce a real proof point:** `XLF` at `1d` (also
`verdict = 'labeled'`, 1008 labeled rows -- the single highest-labeled-row-count 1d cell in the
full 172-05 evidence) was run as a fifth symbol specifically because its `turbulent` bucket
(527 raw rows within the training window) was the only bucket across all 44 labeled 1d cells
confirmed in advance to clear the ~500-row floor. Result: **876 real `feature_ic_scores` rows
now carry `regime_scope = 'symbol_hmm'`, `regime = 'turbulent'`, `reliable = true`** -- direct,
observed proof that a real post-cutover `ic_engine.py --refresh` run writes volatility-keyed
rows, not merely that unit tests pass.

**Post-run verification, all confirmed:**
- Zero rows across the full 5-symbol/1d/this-training_window_end scope carry any retired
  trend label (`trending_up`/`trending_down`/`ranging`/`transition_up`/`transition_down`) --
  direct `psql` count returned 0.
- The one non-pooled `symbol_hmm` row set (XLF's `turbulent` rows) carries a code present in
  `SELECT code FROM controlled_vocabulary WHERE namespace = 'regime_volatility'` (`calm`,
  `elevated`, `turbulent`).
- `cross_sectional`-scope rows in this scope carry `market_regimes` labels (`high_bear`,
  `low_bull`, `low_neutral`, `mid_neutral`, `up_primary_contango`, `up_primary_neutral`) --
  this is correct, not a leak of the retired per-symbol vocabulary; cross-sectional
  stratification is a completely separate labeling system from the per-symbol HMM this phase
  changed.
- `.venv/bin/pytest tests/unit/ -k "ic_engine or ensemble_trainer" -q`: 289 passed before the
  run, 298 passed after (298 = 289 + the 9 new regression tests added in this same plan).
- `ps aux | grep ic_engine.py | grep -v grep` returned nothing after both runs -- no orphaned
  `ProcessPoolExecutor` workers.
- Both runs' `run_complete` log lines report `status: success` (elapsed 352.55s for the
  4-symbol run, 157.97s for the XLF supplement).

**Evidence artifact:** `evidence/172-07-ic-refresh-scoped.json` (`run_type: smoke_test`),
including the symbol-selection rationale and the corpus asset-class-composition note in full.

**Known defect in the plan's own automated verify script, flagged rather than silently
patched:** the script's final assertion (`len({v for v in scope['asset_class'].values()}) >=
2`) is unsatisfiable from real corpus data -- every symbol among the 172-05-labeled `1d` cells
is `asset_class = 'equity'` (verified against both the 80-symbol relabel-eligible set and the
full `instruments` table, which does carry `futures`/`fx` rows but none of them are part of
this ETF corpus). All eight other assertions in the same script pass. The plan's own prose
acceptance criterion explicitly allows this outcome when documented ("The scope spans at least
three distinct asset classes, or the SUMMARY records how many asset classes had labeled 1d
cells and why fewer were used") -- the automated check simply did not encode the same
allowance. Not fixed here (editing the plan's own acceptance bar mid-execution was judged out
of scope); recorded as a plan-authoring gap for whoever next touches this verify block.
