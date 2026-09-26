# 176-05 Scope Consumer Audit

Every `feature_ic_scores` consumer outside `services/ic_engine.py` (covered by plan 176-04
Task 2) and `services/ensemble_trainer.py` (covered by this plan's Task 1) is inventoried
below, with an explicit `DECISION-DRIVING` determination made before the verdict, per the
plan's ordering rule.

Method: `grep -rn "feature_ic_scores" services/ scripts/ src/ api/ --include=*.py` and
`grep -rn "regime_scope" services/ scripts/ src/ api/ --include=*.py`, unioned, deduplicated by
file, minus the two excluded files. `api/` does not exist in this repository (confirmed via
`ls -d api/` -> `No such file or directory`), so both greps warn on it and contribute zero
matches from it; that warning line is preserved verbatim in the raw output below rather than
edited out. 39 files remain in scope.

## Phase-level contract

Rows with `regime_scope='earnings_season'` are measurement-only for Phase 176 and feed no
weighting, emission, lifecycle or promotion decision. Two enforcement points: (1)
`services/ensemble_trainer.py::_eligibility_where` (this plan's Task 1 -- the sole ensemble
training-eligibility gate, all three call sites route through it) and (2)
`services/ic_engine.py`'s in-file IC lifecycle guard (plan 176-04 Task 2 -- isolates the new
`regime_scope` value from the data-contract check so it doesn't surface as a violation). Every
other decision-driving consumer identified below either already excludes the new scope
(ALLOW-LISTED) or was patched in this plan to exclude it (NEEDS-FILTER, patched).

## Summary table

| File | Line(s) inspected | DECISION-DRIVING | Verdict | Patched | Reasoning |
|---|---|---|---|---|---|
| scripts/analysis/equity_regime_separation_gate.py | 120, 153, 305, 319, 329 | DECISION-DRIVING: yes -- Phase 144 promotion-decision gate script (`docs/plans/archive/...phase148-promotion-decision.md`-adjacent regime-separation verdicts) | ALLOW-LISTED | n/a | Every query explicitly filters `regime_scope = 'symbol_hmm'` or `regime_scope = 'cross_sectional'`; a fourth scope value is simply never matched. |
| scripts/analysis/feature_library_dimensionality.py | 149 | DECISION-DRIVING: yes -- feeds feature-library redundancy/governance analysis | ALLOW-LISTED | n/a | The sole `feature_ic_scores` query explicitly filters `AND regime_scope = 'cross_sectional'`. |
| scripts/analysis/_nonlinear_interaction_combiner_shared.py | 509 | DECISION-DRIVING: no -- does not query the table | SCOPE-AGNOSTIC | n/a | Line 509 is a docstring describing `ensemble_trainer.py`'s own behavior, not a query in this file. No `FROM feature_ic_scores` anywhere in the file. |
| scripts/analysis/personal_cost_hurdle_by_tf.py | 104, 120 (pre-patch) | DECISION-DRIVING: yes -- feeds personal-scale/universe-expansion IC-hurdle economic-viability comparisons (the successor work to the closed personal-scale program; the tool is not itself closed) | NEEDS-FILTER | yes | Both queries used the exact `symbol = 'POOLED' AND is_pooled` shape earnings-season pooled cells (176-06) also carry, with no `regime_scope` filter. Added `AND regime_scope <> 'earnings_season'` to both. |
| scripts/analysis/personal_cost_hurdle.py | 329 | DECISION-DRIVING: no -- no query against the table | SCOPE-AGNOSTIC | n/a | Line 329 is a print-string reference to "measured avg ICs in feature_ic_scores"; `grep -n "FROM feature_ic_scores"` returns zero hits in this file. |
| scripts/analysis/personal_edge_paper_screen.py | 85, 100 (pre-patch) | DECISION-DRIVING: yes -- own docstring: "the theory-free shortlist is every FDR-passing pooled cell" that gets "placed against the program's personal hurdle," directly informing construction verdicts | NEEDS-FILTER | yes | Query 1 (`symbol = 'POOLED'`) matches 176-06's pooled shape; query 2 (`is_pooled = false`) matches 176-04's per-symbol in_season/off_season shape. Neither filtered `regime_scope`. Added the exclusion to both. |
| scripts/analysis/per_symbol_regime_candidates_stage2_orthogonality.py | 344 | DECISION-DRIVING: no -- no query against the table | SCOPE-AGNOSTIC | n/a | Line 344 states the file "does NOT need ic_engine/feature_ic_scores after all" -- confirmed no query present. |
| scripts/analysis/phase144_regime_separation_gate.py | 112, 152-155, 323, 331 | DECISION-DRIVING: yes -- Phase 144 promotion-decision gate (D-05 verdict record) | ALLOW-LISTED | n/a | Every query explicitly filters `regime_scope = 'symbol_hmm'` or `regime_scope = 'cross_sectional'` via a parameterized `where` builder. |
| scripts/analysis/regime_boundary_churn_check.py | 96-109 | DECISION-DRIVING: yes -- churn diagnostic reading the actual production `ensemble_weights` table | ALLOW-LISTED (transitive) | n/a | The one query JOINs `feature_ic_scores` to `ensemble_weights` on `fic.regime = ew.regime`; `ensemble_weights` can never contain an earnings-season-derived regime label post-Task-1 (the eligibility exclusion runs upstream of every row that could ever reach `ensemble_weights`), so the JOIN is protected by construction. |
| scripts/analysis/statistical_factor_residual_k_selection_pilot.py | 9 | DECISION-DRIVING: no -- no query against the table | SCOPE-AGNOSTIC | n/a | Line 9 states the file "never touches ctf_momentum, feature_ic_scores, or any downstream IC target" -- confirmed no query present. |
| scripts/analysis/statistical_factor_residual_stage3_ic_falsification.py | 155-180 | DECISION-DRIVING: no -- the query's own function name is `_print_context_baseline`, and both the docstring ("printed for context only, never used as the pass/fail bar") and the print statement itself ("Context only (NOT the pass/fail bar...)") explicitly disclaim any role in the file's verdict, which comes from independently, locally recomputed values on identical dates | SCOPE-AGNOSTIC | n/a | `statistical_factor_residual` is itself closed DEAD (2026-09-01, construction-verdict-ledger.md); the `GROUP BY regime_scope` printout would show a 4th group if earnings-season rows existed for `ctf_momentum` (not in 176-01's `SWEEP_SURVIVORS` list, so unlikely today regardless), but the file's own verdict rule never reads this query's output. |
| scripts/debug/analysis/debug_analyze_feature_ic.py | 37, 59, 94, 131, 164 (pre-patch) | DECISION-DRIVING: yes -- "Run after corpus pipeline completion to review feature predictive quality," writes `docs/analysis/feature_ic_analysis.md`/`.json` explicitly for that review | NEEDS-FILTER | yes | All 5 queries (vintage lookup + overall/by-feature/by-tf/by-regime aggregates) were unfiltered by `regime_scope`, so a 4th scope would silently change every reported mean/count in this feature-quality report. Added the exclusion to all 5. |
| scripts/ops/alpha/ops_canary_integrity_assert.py | 74, 76-86 (pre-patch) | DECISION-DRIVING: yes -- chained into `scripts/ops/corpus/ops_corpus_pipeline_run.sh` (line 161), a HARD-halt corpus-run integrity gate | NEEDS-FILTER | yes | `_CANARY_ROWS_SQL` counted POOLED-family canary clears against a pre-committed Binomial tail bound with no `regime_scope` filter; an unrelated new scope could shift the denominator/tail-bound trigger if canary coverage ever extends there. Added the exclusion to `_CANARY_ROWS_SQL` and the vintage lookup. |
| scripts/ops/alpha/ops_dependence_length_diagnostic.py | 78 (pre-patch) | DECISION-DRIVING: yes -- writes `integrity_monitor` rows that "gate downstream consumers today" per its own docstring | NEEDS-FILTER | yes | Only touchpoint is `_LATEST_VINTAGE_SQL` (a MAX(training_window_end) anchor). Semantically a no-op today -- 176-04-PLAN.md confirms earnings-season conditioning runs inside the same `ic_engine` pass, sharing `training_window_end` -- but patched as defense-in-depth per the plan's SCOPE-AGNOSTIC-requires-DECISION-DRIVING:no rule, and against a future redesign where it runs as a separate pass. |
| scripts/ops/alpha/ops_emission_threshold_sweep.py | 238 | DECISION-DRIVING: no -- no query against the table | SCOPE-AGNOSTIC | n/a | Line 238 is a print-string reference ("current inputs (feature_ic_scores / alpha_ensemble_ic) predate the..."); no `FROM feature_ic_scores` anywhere in the file. |
| scripts/ops/alpha/ops_ensemble_ic_diagnosis.py | 103-111 | DECISION-DRIVING: yes -- operator-facing EIC-04 gate-failure diagnosis, informs remediation | ALLOW-LISTED | n/a | The one direct `feature_ic_scores` query already filters `AND regime_scope = 'cross_sectional'` on the live-schema path; the unfiltered fallback only fires when `regime_scope` doesn't exist as a column at all (pre-RSCOPE-01 schema), which cannot coexist with earnings-season data. File explicitly states "Exit code is always 0 ... not a gate." |
| scripts/ops/alpha/ops_ensemble_weight_compare.py | 21, 58 | DECISION-DRIVING: no -- no query against the table | SCOPE-AGNOSTIC | n/a | Both hits are comments citing `feature_ic_scores.regime`'s naming convention for an unrelated sentinel value; `grep -n "FROM feature_ic_scores"` returns zero hits. |
| scripts/ops/alpha/ops_ic_null_calibration.py | 95, 98-132 (pre-patch) | DECISION-DRIVING: yes -- own docstring: this is "the staged-validation gate that must pass ... before any corpus-wide re-run computes feature_ic_scores CIs via the bootstrap," a real methodology-change decision recorded in `methodology-change-ledger.md` | NEEDS-FILTER | yes | `_BOUNDARY_CELLS_SQL`/`_NULL_CELLS_SQL`/`_STRONG_CELLS_SQL` stratify a CI/FDR-boundary cell sample with no `regime_scope` filter; D-02 already scopes to one `training_window_end` vintage specifically to avoid mixing populations -- the same discipline now applies to the new scope. Added the exclusion to all three plus the vintage lookup. |
| scripts/ops/alpha/ops_ic_shrinkage.py | 95-100, 121-126 (pre-patch) | DECISION-DRIVING: yes -- chained into `scripts/ops/corpus/ops_corpus_pipeline_run.sh` (line 383); Part B is a HARD GATE (D-05) that flips `alpha.ensemble.ic_input` to `'ic_shrunk'`, which `ensemble_trainer.py` reads as an alternate eligibility input column | NEEDS-FILTER | yes | `_RELIABLE_ROWS_SQL` (all reliable rows, unfiltered) feeds the leave-one-out `(group_name, regime, tf)` shrinkage-prior computation; `_POOLED_RELIABLE_CELLS_SQL` used the exact POOLED shape. Even though earnings-season's distinct `regime` labels would likely form their own peer groups in the leave-one-out prior (no cross-contamination of the original three scopes' shrinkage estimates), being included in a HARD GATE's input population at all violates "measurement-only" regardless of numerical inertness. Added the exclusion to both. |
| scripts/ops/alpha/ops_interaction_primitives_pilot.py | 184-193 (pre-patch) | DECISION-DRIVING: yes -- `UPDATE feature_ic_scores SET partial_ic = ...` (line ~571), and `services/ic_engine.py:1602/1613` SELECTs `partial_ic`/`partial_ic_p_value`/`partial_ic_n` back out, so this script's writes flow directly into `ic_engine`'s own persisted output | NEEDS-FILTER | yes | `_load_pooled_cells` used the exact `symbol = 'POOLED', is_pooled = true, regime != '_pooled'` shape with no `regime_scope` filter. Added the exclusion. |
| scripts/ops/alpha/ops_lookahead_horizon_response.py | 167 (pre-patch) | DECISION-DRIVING: yes -- ambiguous; the diagnostic's stated purpose is to replace "guessed bar-counts" with "a real IC-decay curve," directly informing a production `alpha.ic.lookahead.*` APR calibration decision -- resolved to yes per the plan's ambiguity rule | NEEDS-FILTER | yes | Only touchpoint is `_LATEST_VINTAGE_SQL`. Semantically a no-op today (same reasoning as `ops_dependence_length_diagnostic.py` -- confirmed via 176-04-PLAN.md that earnings-season conditioning shares the main run's `training_window_end`), patched as defense-in-depth. The diagnostic itself is "Deliberately NOT regime-stratified" and computes its own IC directly from `market_data_ohlcv_tradeable`/`forward_returns`, never reading `feature_ic_scores` IC content. |
| scripts/ops/alpha/ops_vol_normalized_target_ab.py | 105, 111-122 (pre-patch) | DECISION-DRIVING: yes -- own docstring: Component F, a regime-conditional raw-vs-vol-normalized-target A/B whose PASS could change the production return-target definition | NEEDS-FILTER | yes | `_REGIMES_SQL` enumerated distinct `regime` labels for a symbol with no `regime_scope` filter -- would have pulled in earnings-season's season-qualified labels and tested vol-normalization against a fundamentally different (calendar-, not volatility/trend-) conditioned stratification. `_BASELINE_SQL` had the same gap. Added the exclusion to both plus the vintage lookup. |
| scripts/ops/corpus/ops_corpus_progress.py | 117, 119 | DECISION-DRIVING: no -- pure operator-facing progress dashboard; not chained into `ops_corpus_pipeline_run.sh` or any other runner, writes nothing, gates nothing | NEEDS-FILTER | no (documented, left unpatched per plan's explicit allowance for DECISION-DRIVING:no rows) | `ic_rows`/`ic_symbols` counts `WHERE is_pooled = false` with no `regime_scope` filter -- 176-04's per-symbol in_season/off_season cells share that shape and would inflate the "Step 4 IC Engine" count beyond the comment's own "3 regimes" completeness-math assumption, making the progress percentage cosmetically misleading. Not decision-driving: purely informational, doesn't feed a promotion/gating/weighting/emission/lifecycle/deployment decision. Fix: add `AND regime_scope <> 'earnings_season'` to both COUNT queries at lines 117 and 119. |
| scripts/ops/corpus/ops_cost_hurdle_calibration.py | 257-264 (pre-patch) | DECISION-DRIVING: yes -- writes `config_state` (`alpha.quant.cost_hurdle.*`, `alpha.quant.threshold.*`) via `ConfigService.set`, a decision-driving write per the plan's own trigger list | NEEDS-FILTER | yes | Step 3's gap-contamination `ic_by_tf` query (`GROUP BY fis.tf`, no scope filter) feeds a followup-todo finding correlated against per-tf average IC. Added the exclusion. Steps 1/2 (the actual config_state writes) read `alpha_events`, not `feature_ic_scores` -- confirmed no other touchpoint in this file. |
| scripts/ops/corpus/ops_ic_fingerprint_equivalence.py | 106, 145 | DECISION-DRIVING: no -- a manual correctness-proof harness for `ic_engine.py`'s fingerprint mechanism, run against a dedicated non-production `--training-window-end`; refuses to run if production rows already exist at that window | SCOPE-AGNOSTIC | n/a | `regime_scope` is one of the VALUE columns compared for run-A-vs-run-B equivalence, not a row-selection filter -- a 4th scope value, if present in the dedicated test window, is compared exactly like any other column, which is correct behavior for an equivalence proof, not a contamination risk. |
| scripts/ops/corpus/ops_known_corrupt_print_cleanup.py | 174 (pre-patch) | DECISION-DRIVING: yes -- writes `integrity_monitor`/`price_sanity_status`, a corpus data-quality gate consulted by every downstream feature computed from raw OHLCV | NEEDS-FILTER | yes | Only touchpoint is `_LATEST_TRAINING_WINDOW_END_SQL`, used solely for a report display string. Semantically a no-op today (same reasoning as the other vintage-lookup-only files), patched as defense-in-depth. |
| scripts/ops/corpus/ops_oos_holdout_eval.py | 250-261 (pre-patch) | DECISION-DRIVING: yes -- resolved from ambiguous to yes: despite the module docstring's "never a promotion gate" disclaimer, `_read_in_sample_qualifying_count`'s result is a DIRECT input to this script's own computed drop-verdict (unlike the stage3_ic_falsification case, where the feature_ic_scores query is inert context alongside an independently-computed pass/fail bar) | NEEDS-FILTER | yes | The in-sample qualifying count had no `regime_scope` filter, so it would be inflated by earnings-season rows relative to the true three-scope in-sample baseline the OOS comparison is meant to validate against. Added the exclusion. |
| services/_batch_utils.py | 195, 344, 456, 969 | DECISION-DRIVING: no -- shared Ring-2 write-session/hardened-table infra with no query or scope-discriminating logic of its own | SCOPE-AGNOSTIC | n/a | All 4 hits are either a frozenset of table names needing write-session protection or comments; no `SELECT`/`WHERE` against `feature_ic_scores` content anywhere in this file. |
| services/cross_sectional_regime_model.py | 330, 337 | DECISION-DRIVING: no -- no query against the table | SCOPE-AGNOSTIC | n/a | Both hits are the LABEL-VOCABULARY-UNIQUENESS INVARIANT docstring (RESEARCH.md Pitfall 4); confirmed no `FROM feature_ic_scores` in this file. |
| services/service_auditor.py | 109, 111 | DECISION-DRIVING: no -- no query against the table | SCOPE-AGNOSTIC | n/a | Both hits are `_DAG_ORDER` comments describing the ic-engine/ensemble-trainer pipeline stage relationship; no query present. |
| src/intelligence/ensemble/feature_selector.py | 2, 6-16, 79-81 | DECISION-DRIVING: yes -- own docstring: "Feature selection from feature_ic_scores for ensemble weight derivation" | ALLOW-LISTED (transitive) | n/a | "Pure functions only -- no DB imports, no Kafka imports." Its own docstring states input rows "must already be filtered by ensemble_trainer.py's `_eligibility_where()`" before reaching this module -- Task 1's exclusion is upstream of every call site. |
| src/intelligence/regime_signals/breadth_vol.py | 39 | DECISION-DRIVING: no -- no query against the table | SCOPE-AGNOSTIC | n/a | Comment describing downstream label propagation; no query in this file (it's a regime-signal module writing to `market_regimes`, not `feature_ic_scores`). |
| src/intelligence/regime_signals/commodity_momentum_ts.py | 19 | DECISION-DRIVING: no -- no query against the table | SCOPE-AGNOSTIC | n/a | Same LABEL-VOCABULARY-NON-OVERLAP docstring pattern as the other regime_signals modules; no query. |
| src/intelligence/regime_signals/curve_credit.py | 19, 22, 28, 46 | DECISION-DRIVING: no -- no query against the table | SCOPE-AGNOSTIC | n/a | Same pattern; no query. |
| src/intelligence/regime_signals/fx_dollar_carry.py | 19 | DECISION-DRIVING: no -- no query against the table | SCOPE-AGNOSTIC | n/a | Same pattern; no query. |
| src/intelligence/statistics/ic_math.py | 377, 933 | DECISION-DRIVING: no -- no query against the table | SCOPE-AGNOSTIC | n/a | Both hits are docstring/comment references; this is a pure-math module (`_vectorized_ic`, `_fisher_z_ci`, etc.), no DB access. |
| src/observability/corpus_manifest.py | 19-20 | DECISION-DRIVING: no -- no query against the table | SCOPE-AGNOSTIC | n/a | Both hits are a schema-example dict inside a module docstring illustrating the manifest JSON shape; not executable, not a query. |
| src/observability/corpus_manifest_verifier.py | 281-288, 296-303 (pre-patch) | DECISION-DRIVING: yes -- `ops_corpus_final_verification.py`'s own docstring: "crash-loud gate before Phase 141 ... Run after corpus_pipeline_run.py completes to validate before consuming alpha_events" | NEEDS-FILTER | yes | Check 2 ("POOLED rows exist for all TFs") and Check 3 ("all lookaheads present per TF") both used `WHERE symbol = 'POOLED' AND regime != '_pooled'` with no `regime_scope` filter -- a completeness check that could be fooled into a false PASS by earnings-season rows existing for a TF where the real three-scope population is actually missing. Added the exclusion to both checks. Checks 5 and 7 were left as-is: Check 5 (NULL regime labels) is a genuine data-integrity check that should fire regardless of scope; Check 7 (training-window-end consistency) is unaffected since earnings-season rows share the same `training_window_end` as the rest of the run (confirmed via 176-04-PLAN.md). |
| src/observability/metrics.py | 1114 | DECISION-DRIVING: no -- no query against the table | SCOPE-AGNOSTIC | n/a | A metric help-text string ("Cells with committed feature_ic_scores row..."); not a query. |

## Raw grep output

### `grep -rn "feature_ic_scores" services/ scripts/ src/ api/ --include=*.py`

```
ugrep: warning: api/: No such file or directory
services/cross_sectional_regime_model.py:330:    LABEL-VOCABULARY-UNIQUENESS INVARIANT (RESEARCH.md Pitfall 4): feature_ic_scores
services/cross_sectional_regime_model.py:337:    would collide under the same regime_label string in downstream feature_ic_scores
services/ensemble_trainer.py:112:    """Build (base, full) eligibility WHERE clauses for feature_ic_scores.
services/ensemble_trainer.py:130:    # feature_ic_scores.regime_scope is NOT NULL (migration 187, re-asserted in
services/ensemble_trainer.py:222:# feature_ic_scores column each alpha.ensemble.ic_input value reads from (E1, D-05).
services/ensemble_trainer.py:235:    """Resolve alpha.ensemble.ic_input to its source feature_ic_scores column.
services/ensemble_trainer.py:499:    n_ic = await conn.fetchval(f"SELECT count(*) FROM feature_ic_scores WHERE {eligibility_where}")
services/ensemble_trainer.py:507:            "EnsembleTrainer startup gate FAILED: no cross-sectional feature_ic_scores rows "
services/ensemble_trainer.py:514:    # finished -- ic_engine.py is the sole writer of feature_ic_scores, and this is
services/ensemble_trainer.py:591:    """Batch compute service: feature_ic_scores → ensemble_weights + ensemble_alpha.
services/ensemble_trainer.py:725:                FROM feature_ic_scores
services/ensemble_trainer.py:762:                FROM feature_ic_scores
services/ensemble_trainer.py:881:        # cutover -- it reads a feature_ic_scores COLUMN that ic_engine stamps, and
services/ensemble_trainer.py:889:            FROM feature_ic_scores
services/_batch_utils.py:195:# Previously a hardcoded `frozenset({"feature_vectors", "feature_ic_scores"})`. The two
services/_batch_utils.py:344:_WRITE_SESSION_HARDENED_TABLES = frozenset({"feature_vectors", "feature_ic_scores"})
services/_batch_utils.py:456:    hypertable concurrently (ic_engine.py's two feature_ic_scores UPDATE call sites were
services/_batch_utils.py:969:    this reverse-lookup, shared by every ops script that maps a `feature_ic_scores.
services/service_auditor.py:109:    "indicagent-ic-engine": 8,  # oneshot; Spearman IC -> feature_ic_scores
services/service_auditor.py:111:    "indicagent-ensemble-trainer": 8,  # oneshot; feature_ic_scores -> ensemble_weights + ensemble_alpha
scripts/ops/corpus/ops_oos_holdout_eval.py:5:qualifying-feature count against the existing in-sample feature_ic_scores population.
scripts/ops/corpus/ops_oos_holdout_eval.py:17:    feature_ic_scores (also used by services.ic_engine and services.ensemble_ic_engine).
scripts/ops/corpus/ops_oos_holdout_eval.py:251:    """Query existing feature_ic_scores for the in-sample qualifying-cell count.
scripts/ops/corpus/ops_oos_holdout_eval.py:257:        "SELECT count(*) FROM feature_ic_scores "
scripts/ops/alpha/ops_canary_integrity_assert.py:8:feature_ic_scores for
scripts/ops/alpha/ops_canary_integrity_assert.py:44:(ic_engine) -- feature_ic_scores must exist before this gate has anything to read.
scripts/ops/alpha/ops_canary_integrity_assert.py:74:_LATEST_VINTAGE_SQL = "SELECT MAX(training_window_end) FROM feature_ic_scores"
scripts/ops/alpha/ops_canary_integrity_assert.py:81:    FROM feature_ic_scores s
scripts/ops/alpha/ops_canary_integrity_assert.py:162:            "no canary rows found for the latest feature_ic_scores vintage -- the "
scripts/ops/corpus/ops_corpus_progress.py:115:    # Step 4 — IC Engine: feature_ic_scores rows
scripts/ops/corpus/ops_corpus_progress.py:117:    ic_rows = int(scalar("SELECT COUNT(*) FROM feature_ic_scores WHERE is_pooled = false"))
scripts/ops/corpus/ops_corpus_progress.py:119:        scalar("SELECT COUNT(DISTINCT symbol) FROM feature_ic_scores WHERE is_pooled = false")
scripts/ops/corpus/ops_known_corrupt_print_cleanup.py:174:_LATEST_TRAINING_WINDOW_END_SQL = "SELECT max(training_window_end) FROM feature_ic_scores"
scripts/ops/corpus/ops_known_corrupt_print_cleanup.py:239:        "<none found -- run: SELECT max(training_window_end) FROM feature_ic_scores>"
scripts/analysis/personal_cost_hurdle.py:329:        "measured avg ICs in feature_ic_scores at the same horizon (e.g. the range/vol "
scripts/ops/alpha/ops_ic_null_calibration.py:26:`feature_ic_scores`, matching the existing "latest vintage" convention used by
scripts/ops/alpha/ops_ic_null_calibration.py:31:is what production actually persists to `feature_ic_scores.n_independent`
scripts/ops/alpha/ops_ic_null_calibration.py:52:any corpus-wide re-run computes feature_ic_scores CIs via the bootstrap.
scripts/ops/alpha/ops_ic_null_calibration.py:95:_LATEST_VINTAGE_SQL = "SELECT max(training_window_end) FROM feature_ic_scores"
scripts/ops/alpha/ops_ic_null_calibration.py:101:    FROM feature_ic_scores
scripts/ops/alpha/ops_ic_null_calibration.py:113:    FROM feature_ic_scores
scripts/ops/alpha/ops_ic_null_calibration.py:125:    FROM feature_ic_scores
scripts/ops/alpha/ops_ic_null_calibration.py:399:            print("ERROR: feature_ic_scores is empty -- nothing to sample.")
scripts/ops/alpha/ops_vol_normalized_target_ab.py:14:return baseline already stored in feature_ic_scores for the same (tf, regime,
scripts/ops/alpha/ops_vol_normalized_target_ab.py:19:`forward_returns`/`feature_ic_scores`. If vol-normalized rankings are materially
scripts/ops/alpha/ops_vol_normalized_target_ab.py:29:rebuilds feature_ic_scores under the corrected pipeline -- Plan 07 re-invokes this same
scripts/ops/alpha/ops_vol_normalized_target_ab.py:34:  - raw baseline: feature_ic_scores.passes_fdr (already computed by production, whatever
scripts/ops/alpha/ops_vol_normalized_target_ab.py:54:market_regimes / feature_ic_scores. Recomputed vol-normalized IC values are NOT persisted
scripts/ops/alpha/ops_vol_normalized_target_ab.py:105:_LATEST_VINTAGE_SQL = "SELECT max(training_window_end) FROM feature_ic_scores"
scripts/ops/alpha/ops_vol_normalized_target_ab.py:111:    SELECT DISTINCT regime FROM feature_ic_scores
scripts/ops/alpha/ops_vol_normalized_target_ab.py:119:    FROM feature_ic_scores
scripts/ops/alpha/ops_vol_normalized_target_ab.py:454:            print("ERROR: feature_ic_scores is empty -- nothing to sample.")
scripts/ops/alpha/ops_emission_threshold_sweep.py:238:            "current inputs (feature_ic_scores / alpha_ensemble_ic) predate the "
scripts/ops/alpha/ops_ic_shrinkage.py:8:(A) Compute pass: for every `reliable = true` `feature_ic_scores` row, shrink
scripts/ops/alpha/ops_ic_shrinkage.py:74:# feature_ic_scores composite PK (services/_batch_utils.py::bulk_update_by_key key_cols).
scripts/ops/alpha/ops_ic_shrinkage.py:98:    FROM feature_ic_scores
scripts/ops/alpha/ops_ic_shrinkage.py:110:# feature_ic_scores row names either tombstone) but a BEFORE/AFTER row-count
scripts/ops/alpha/ops_ic_shrinkage.py:123:    FROM feature_ic_scores
scripts/ops/alpha/ops_ic_shrinkage.py:170:    for every reliable `feature_ic_scores` row, via a leave-one-out
scripts/ops/alpha/ops_ic_shrinkage.py:478:            # feature_ic_scores is a compressed hypertable -- a single UPDATE against a
scripts/ops/alpha/ops_ic_shrinkage.py:483:            with _write_session(sync_conn, "feature_ic_scores"):
scripts/ops/alpha/ops_ic_shrinkage.py:486:                    table="feature_ic_scores",
scripts/analysis/equity_regime_separation_gate.py:11:Same reused machinery, no new statistics invented: `feature_ic_scores.mean(ic_value)` grouped
scripts/analysis/equity_regime_separation_gate.py:27:in-flight corpus. STEP 0 checks for the existence of ANY feature_ic_scores row carrying
scripts/analysis/equity_regime_separation_gate.py:119:            FROM feature_ic_scores
scripts/analysis/equity_regime_separation_gate.py:128:            f"Zero feature_ic_scores rows found with regime_scope='symbol_hmm' for any of "
scripts/analysis/equity_regime_separation_gate.py:168:        FROM feature_ic_scores
scripts/analysis/phase144_regime_separation_gate.py:14:Question 3) -- writing it fresh against feature_ic_scores.regime_scope is this
scripts/analysis/phase144_regime_separation_gate.py:34:feature_ic_scores row carrying a `rates` cross-sectional regime label -- that
scripts/analysis/phase144_regime_separation_gate.py:111:            FROM feature_ic_scores
scripts/analysis/phase144_regime_separation_gate.py:121:        cur.execute("SELECT max(computed_at) AS latest, count(*) AS n FROM feature_ic_scores")
scripts/analysis/phase144_regime_separation_gate.py:126:            f"Zero feature_ic_scores rows found with regime_scope='cross_sectional' and a "
scripts/analysis/phase144_regime_separation_gate.py:129:            f"(Plan 05) has run against a rebuilt corpus. Overall feature_ic_scores state: "
scripts/analysis/phase144_regime_separation_gate.py:135:        f"Found {len(rates_rows)} rates-vocabulary regime labels in feature_ic_scores: "
scripts/analysis/phase144_regime_separation_gate.py:136:        f"{[(r[0], r[1], str(r[2])) for r in rates_rows]}. Overall feature_ic_scores state: "
scripts/analysis/phase144_regime_separation_gate.py:167:        FROM feature_ic_scores
scripts/analysis/phase144_regime_separation_gate.py:353:        help="Timeframe(s) to measure (default: all tfs present in feature_ic_scores)",
scripts/analysis/statistical_factor_residual_k_selection_pilot.py:9:it never touches ctf_momentum, feature_ic_scores, or any downstream IC target, so there
scripts/analysis/personal_cost_hurdle_by_tf.py:18:IC at that tf's own `lookahead_bars` values already used in feature_ic_scores (5m:
scripts/analysis/personal_cost_hurdle_by_tf.py:25:Read-only against feature_vectors / feature_ic_scores. No writes.
scripts/analysis/personal_cost_hurdle_by_tf.py:104:            SELECT DISTINCT lookahead_bars FROM feature_ic_scores
scripts/analysis/personal_cost_hurdle_by_tf.py:120:            FROM feature_ic_scores
scripts/analysis/personal_cost_hurdle_by_tf.py:183:        "exact (tf, lookahead_bars) in feature_ic_scores, not an assumption. This is a "
scripts/ops/alpha/ops_dependence_length_diagnostic.py:78:_LATEST_VINTAGE_SQL = "SELECT max(training_window_end) FROM feature_ic_scores"
scripts/ops/alpha/ops_dependence_length_diagnostic.py:85:# -- 'feature=<name>|tf=<tf>', no new table, no new column on feature_ic_scores.
scripts/ops/alpha/ops_dependence_length_diagnostic.py:204:            print("ERROR: feature_ic_scores is empty -- no vintage to anchor the sample.")
scripts/analysis/personal_edge_paper_screen.py:85:            FROM feature_ic_scores
scripts/analysis/personal_edge_paper_screen.py:100:            FROM feature_ic_scores
scripts/analysis/regime_boundary_churn_check.py:77:# lives only in feature_ic_scores, not ensemble_weights.
scripts/analysis/regime_boundary_churn_check.py:80:# feature_ic_scores row ensemble_trainer.py actually used. select_features_per_stratum picks,
scripts/analysis/regime_boundary_churn_check.py:101:        FROM feature_ic_scores fic
scripts/ops/corpus/ops_cost_hurdle_calibration.py:5:`alpha_events` / `forward_returns` / `feature_ic_scores` corpus and:
scripts/ops/corpus/ops_cost_hurdle_calibration.py:16:  against `feature_ic_scores`. ALWAYS reports the finding; writes a follow-up
scripts/ops/corpus/ops_cost_hurdle_calibration.py:28:  forward_returns / feature_ic_scores; all writes go through ConfigService
scripts/ops/corpus/ops_cost_hurdle_calibration.py:262:        FROM feature_ic_scores fis
scripts/ops/alpha/ops_lookahead_horizon_response.py:167:_LATEST_VINTAGE_SQL = "SELECT max(training_window_end) FROM feature_ic_scores"
scripts/ops/alpha/ops_lookahead_horizon_response.py:362:        "the default MAX(training_window_end) lookup from feature_ic_scores. Needed "
scripts/ops/alpha/ops_lookahead_horizon_response.py:365:        "market_data_ohlcv_tradeable and never reads feature_ic_scores/forward_returns "
scripts/ops/alpha/ops_lookahead_horizon_response.py:367:        "the pipeline run that's populating it) works just as well as feature_ic_scores' "
scripts/ops/alpha/ops_lookahead_horizon_response.py:437:                "ERROR: feature_ic_scores is empty -- no vintage to anchor the sample. "
scripts/analysis/statistical_factor_residual_stage3_ic_falsification.py:22:2. Comparison bar. `feature_ic_scores` for (ctf_momentum, tf=1d) holds 117 POOLED rows alone
scripts/analysis/statistical_factor_residual_stage3_ic_falsification.py:28:   freedom. The historical feature_ic_scores POOLED numbers are printed for context only,
scripts/analysis/statistical_factor_residual_stage3_ic_falsification.py:38:     (matches feature_ic_scores' is_pooled=true, regime_scope='pooled')
scripts/analysis/statistical_factor_residual_stage3_ic_falsification.py:45:   feature_ic_scores itself uses (separate regime_scope rows, not FDR-corrected against
scripts/analysis/statistical_factor_residual_stage3_ic_falsification.py:64:and feature_ic_scores (context only). No writes.
scripts/analysis/statistical_factor_residual_stage3_ic_falsification.py:160:            FROM feature_ic_scores
scripts/analysis/statistical_factor_residual_stage3_ic_falsification.py:163:                  SELECT max(training_window_end) FROM feature_ic_scores
scripts/analysis/statistical_factor_residual_stage3_ic_falsification.py:173:        "historical feature_ic_scores POOLED rows, ctf_momentum, tf=1d, latest window"
scripts/ops/alpha/ops_ensemble_ic_diagnosis.py:6:breakdown, regime coverage) reading alpha_ensemble_ic + feature_ic_scores, scoped to
scripts/ops/alpha/ops_ensemble_ic_diagnosis.py:76:            # to this DB yet -- fall back to an unfiltered feature_ic_scores count with a
scripts/ops/alpha/ops_ensemble_ic_diagnosis.py:80:                "WHERE table_name = 'feature_ic_scores' AND column_name = 'regime_scope')"
scripts/ops/alpha/ops_ensemble_ic_diagnosis.py:105:                    "SELECT count(*) FROM feature_ic_scores "
scripts/ops/alpha/ops_ensemble_ic_diagnosis.py:110:                    "SELECT count(*) FROM feature_ic_scores WHERE ic_ci_lower > 0"
scripts/ops/alpha/ops_ensemble_ic_diagnosis.py:158:                "> Note: feature_ic_scores.regime_scope not present on this DB — the "
scripts/ops/alpha/ops_ensemble_ic_diagnosis.py:163:            f"Comparison context: feature_ic_scores rows with ic_ci_lower > 0 "
src/observability/metrics.py:1114:        "Cells with committed feature_ic_scores row; labels symbol, tf, regime. "
scripts/ops/alpha/ops_interaction_primitives_pilot.py:8:parents? Reuses already-measured cross-sectional feature_ic_scores rows
scripts/ops/alpha/ops_interaction_primitives_pilot.py:186:        "FROM feature_ic_scores "
scripts/ops/alpha/ops_interaction_primitives_pilot.py:490:                    "feature_ic_scores rows found for the interaction-primitive cohort -- "
scripts/ops/alpha/ops_interaction_primitives_pilot.py:563:                # feature_ic_scores is a compressed hypertable -- bracket this batch write
scripts/ops/alpha/ops_interaction_primitives_pilot.py:569:                async with _write_session(conn, "feature_ic_scores"), conn.transaction():
scripts/ops/alpha/ops_interaction_primitives_pilot.py:571:                        "UPDATE feature_ic_scores SET partial_ic = $1, "
scripts/analysis/feature_library_dimensionality.py:8:1. **IC-profile independence** (feature_ic_scores, per-symbol): a feature's per-symbol IC
scripts/analysis/feature_library_dimensionality.py:18:   (todos 280/283 -- unrouted expansion symbols are absent from feature_ic_scores), so
scripts/analysis/feature_library_dimensionality.py:146:            FROM feature_ic_scores
scripts/analysis/feature_library_dimensionality.py:311:        profile_corr, "IC-profile effective rank (feature_ic_scores, per-symbol)", profile_dim
scripts/analysis/_nonlinear_interaction_combiner_shared.py:509:    ensemble_trainer.py selects features from BH-FDR-passing `feature_ic_scores` rows, applies a
scripts/debug/analysis/debug_analyze_feature_ic.py:5:Reads feature_ic_scores table and produces IC distribution analysis by feature,
scripts/debug/analysis/debug_analyze_feature_ic.py:8:Requires feature_ic_scores table populated with IC data.
scripts/debug/analysis/debug_analyze_feature_ic.py:35:    """Get the latest training_window_end from feature_ic_scores."""
scripts/debug/analysis/debug_analyze_feature_ic.py:37:        cur.execute("SELECT MAX(training_window_end) FROM feature_ic_scores")
scripts/debug/analysis/debug_analyze_feature_ic.py:58:            FROM feature_ic_scores
scripts/debug/analysis/debug_analyze_feature_ic.py:93:            FROM feature_ic_scores
scripts/debug/analysis/debug_analyze_feature_ic.py:130:            FROM feature_ic_scores
scripts/debug/analysis/debug_analyze_feature_ic.py:163:            FROM feature_ic_scores
scripts/debug/analysis/debug_analyze_feature_ic.py:280:            _logger.error("No data found in feature_ic_scores")
scripts/debug/analysis/debug_analyze_feature_ic.py:281:            print("ERROR: No data found in feature_ic_scores. Has corpus pipeline completed?")
services/ic_engine.py:7:feature_ic_scores.
services/ic_engine.py:176:# The feature_ic_scores PK includes regime (NOT NULL), so we can't store NULL.
services/ic_engine.py:192:# feature_ic_scores.symbol is NOT NULL, so we use a string sentinel.
services/ic_engine.py:201:# only prior user). feature_ic_scores.cluster_id is smallint (max 32767); ~40
services/ic_engine.py:244:    """Resolve the label vocabulary a feature_ic_scores row's regime column draws from.
services/ic_engine.py:365:    INSERT INTO feature_ic_scores (
services/ic_engine.py:914:# the IC VALUES written to feature_ic_scores -- must invalidate the fingerprint) or
services/ic_engine.py:938:        # a scale changes which feature_ic_scores rows get written, same class of
services/ic_engine.py:965:        # feature_ic_scores rows written by this file today. Classified COMPUTATIONAL
services/ic_engine.py:975:        # comment) -- toggling it changes WHICH feature_ic_scores rows exist
services/ic_engine.py:983:        # carried-forward vs recomputed, moving feature_ic_scores content directly.
services/ic_engine.py:1023:        # feature_ic_scores rows are already written; never affects the rows
services/ic_engine.py:1529:    fingerprint-valid sibling hits feature_ic_scores' ON CONFLICT ... DO
services/ic_engine.py:1560:    DELETE FROM feature_ic_scores
services/ic_engine.py:1567:# Cross-sectional variant: feature_ic_scores.symbol is always the 'POOLED' sentinel
services/ic_engine.py:1573:    DELETE FROM feature_ic_scores
services/ic_engine.py:1583:# ever leave the pre-delete row still in feature_ic_scores, never a silently-lost row with
services/ic_engine.py:1584:# nothing archived). Column list is explicit (not SELECT *) so a future feature_ic_scores
services/ic_engine.py:1587:# fp.symbol is bound as a SEPARATE parameter (%(fp_symbol)s) from feature_ic_scores.symbol
services/ic_engine.py:1588:# (%(symbol)s) because ic_cell_fingerprints and feature_ic_scores use DIFFERENT symbol-key
services/ic_engine.py:1589:# conventions for cross-sectional cells: feature_ic_scores.symbol is always the 'POOLED'
services/ic_engine.py:1596:    INSERT INTO feature_ic_scores_history (
services/ic_engine.py:1618:    FROM feature_ic_scores fis
services/ic_engine.py:1633:    INSERT INTO feature_ic_scores_history (
services/ic_engine.py:1655:    FROM feature_ic_scores fis
services/ic_engine.py:1695:# rows -- belt-and-suspenders, since no feature_ic_scores row has ever named
services/ic_engine.py:1699:    UPDATE feature_ic_scores fis
services/ic_engine.py:1812:    A run that 'succeeds' with empty feature_ic_scores is a data-integrity
services/ic_engine.py:1829:    # cutover (feature_ic_scores vintage separation depends on it staying byte-for-byte
services/ic_engine.py:2632:            # feature_ic_scores unique index (feature_name, symbol, tf, regime,
services/ic_engine.py:4005:            # unique index feature_ic_scores_cross_sectional_uq (feature_name,
services/ic_engine.py:4545:    persisted on the result row -- feature_ic_scores has no regime_group column;
services/ic_engine.py:4649:                        FROM feature_ic_scores
services/ic_engine.py:5066:    """Write IC results to feature_ic_scores in main process.
services/ic_engine.py:5191:    """Write one symbol's already-computed rows to feature_ic_scores immediately
services/ic_engine.py:5252:    """Write cross-sectional IC results to feature_ic_scores in main process.
services/ic_engine.py:5265:    """Write one cross-sectional cell's rows to feature_ic_scores immediately
services/ic_engine.py:5278:    Called right after the corresponding feature_ic_scores rows are durable --
services/ic_engine.py:5292:# feature_ic_scores' primary key (todo 307) -- same 6-column shape
services/ic_engine.py:5350:            FROM feature_ic_scores
services/ic_engine.py:5376:    # feature_ic_scores is a compressed hypertable -- this UPDATE is corpus-wide
services/ic_engine.py:5386:    with _write_session(conn, "feature_ic_scores"):
services/ic_engine.py:5389:            table="feature_ic_scores",
services/ic_engine.py:5607:    Falls back to MAX(training_window_end) in feature_ic_scores strictly BEFORE this
services/ic_engine.py:5627:            "SELECT max(training_window_end) FROM feature_ic_scores WHERE training_window_end < %s",
services/ic_engine.py:5867:            FROM feature_ic_scores fis
services/ic_engine.py:5978:        # market_regimes is a data-contract violation between feature_ic_scores
services/ic_engine.py:6789:            # regime_group/tf/regime (feature_ic_scores has no regime_group column),
services/ic_engine.py:6801:                # feature_ic_scores is a compressed hypertable -- this UPDATE can hit
services/ic_engine.py:6805:                with _write_session(conn, "feature_ic_scores"):
services/ic_engine.py:6843:            # Each symbol's rows are written to feature_ic_scores immediately
services/ic_engine.py:6899:                # one slow one. Written to feature_ic_scores immediately (todo
services/ic_engine.py:7039:                    # (feature_ic_scores' 'POOLED' sentinel) -- see _ARCHIVE_BEFORE_DELETE_SQL's
services/ic_engine.py:7098:                # already durable in feature_ic_scores by this point (written
services/ic_engine.py:7155:                        FROM feature_ic_scores
services/ic_engine.py:7167:                        FROM feature_ic_scores
services/ic_engine.py:7177:                        "SELECT COUNT(*) FROM feature_ic_scores WHERE training_window_end = %s",
services/ic_engine.py:7201:                table_name="feature_ic_scores",
src/observability/corpus_manifest_verifier.py:283:                FROM feature_ic_scores
src/observability/corpus_manifest_verifier.py:298:                FROM feature_ic_scores
src/observability/corpus_manifest_verifier.py:331:                FROM feature_ic_scores
src/observability/corpus_manifest_verifier.py:359:                    FROM feature_ic_scores
src/observability/corpus_manifest_verifier.py:367:                        f"{inconsistent_count} feature_ic_scores rows have "
scripts/ops/corpus/ops_ic_fingerprint_equivalence.py:11:feature_ic_scores rows on the FULL value set, including bh_adjusted_p/passes_fdr (populated
scripts/ops/corpus/ops_ic_fingerprint_equivalence.py:25:therefore REFUSES to run (exit nonzero) if any feature_ic_scores rows already exist for the
scripts/ops/corpus/ops_ic_fingerprint_equivalence.py:72:# feature_ic_scores columns compared for VALUE equivalence -- everything except the PK
scripts/ops/corpus/ops_ic_fingerprint_equivalence.py:76:# feature_ic_scores`), NOT migration 156's original DDL -- the live table has drifted well
scripts/ops/corpus/ops_ic_fingerprint_equivalence.py:148:    FROM feature_ic_scores
scripts/ops/corpus/ops_ic_fingerprint_equivalence.py:212:                f"FATAL: {len(existing)} feature_ic_scores row(s) already exist for this "
scripts/ops/corpus/ops_ic_fingerprint_equivalence.py:345:    """Deletes every feature_ic_scores/ic_cell_fingerprints row at this test's dedicated
scripts/ops/corpus/ops_ic_fingerprint_equivalence.py:353:            "DELETE FROM feature_ic_scores WHERE tf = ANY($1) AND training_window_end = $2",
scripts/ops/corpus/ops_ic_fingerprint_equivalence.py:364:        feature_ic_scores=result_scores,
scripts/ops/corpus/ops_ic_fingerprint_equivalence.py:391:    print(f"[run A] snapshot: {len(snap_a)} feature_ic_scores rows")
scripts/ops/corpus/ops_ic_fingerprint_equivalence.py:398:    print(f"[run B] snapshot: {len(snap_b)} feature_ic_scores rows")
scripts/ops/corpus/ops_ic_fingerprint_equivalence.py:437:        f"feature_ic_scores/ic_cell_fingerprints at training_window_end="
scripts/ops/alpha/ops_ensemble_weight_compare.py:21:regime sentinel (the convention already used by `feature_ic_scores.regime` — see
scripts/ops/alpha/ops_ensemble_weight_compare.py:58:# D-14: aggregate-across-regime sentinel already used by feature_ic_scores.regime (see
scripts/analysis/per_symbol_regime_candidates_stage2_orthogonality.py:344:        "does NOT need ic_engine/feature_ic_scores after all, just forward_returns + "
src/intelligence/regime_signals/fx_dollar_carry.py:19:Label-vocabulary non-overlap invariant (Pitfall 4, feature_ic_scores has no regime_group
src/intelligence/regime_signals/commodity_momentum_ts.py:19:Label-vocabulary non-overlap invariant (Pitfall 4, feature_ic_scores has no regime_group
src/intelligence/regime_signals/curve_credit.py:22:LABEL-VOCABULARY NON-OVERLAP INVARIANT (RESEARCH.md Pitfall 4): feature_ic_scores has no
src/intelligence/regime_signals/curve_credit.py:28:regimes would silently coalesce under the same `regime` string in feature_ic_scores.
src/intelligence/regime_signals/curve_credit.py:46:downstream market_regimes label, feature_ic_scores regime stratum, and ensemble_weights/
src/observability/corpus_manifest.py:19:        "feature_ic_scores": {
src/observability/corpus_manifest.py:20:            "table": "feature_ic_scores",
src/intelligence/ensemble/feature_selector.py:2:Feature selection from feature_ic_scores for ensemble weight derivation.
src/intelligence/ensemble/feature_selector.py:79:        List of dicts from feature_ic_scores, pre-filtered to one (symbol, tf, regime)
src/intelligence/regime_signals/breadth_vol.py:39:another. Changing this changes every downstream market_regimes label, feature_ic_scores
src/intelligence/statistics/ic_math.py:377:    `forward_returns`/`feature_ic_scores`). See
src/intelligence/statistics/ic_math.py:933:    prior feature_ic_scores row exists for this cell.
```

### `grep -rn "regime_scope" services/ scripts/ src/ api/ --include=*.py`

```
ugrep: warning: api/: No such file or directory
services/ensemble_trainer.py:124:    # Phase 176 introduced a fourth regime_scope value, 'earnings_season', for
services/ensemble_trainer.py:130:    # feature_ic_scores.regime_scope is NOT NULL (migration 187, re-asserted in
services/ensemble_trainer.py:134:        " AND regime_scope <> 'earnings_season'"
scripts/analysis/phase144_regime_separation_gate.py:7:per-symbol HMM regime labels (regime_scope='symbol_hmm') against the NEW `rates`
scripts/analysis/phase144_regime_separation_gate.py:8:cross-sectional group's labels (regime_scope='cross_sectional', symbol='POOLED',
scripts/analysis/phase144_regime_separation_gate.py:14:Question 3) -- writing it fresh against feature_ic_scores.regime_scope is this
scripts/analysis/phase144_regime_separation_gate.py:67:# Rows carrying any of these labels under regime_scope='cross_sectional' can only
scripts/analysis/phase144_regime_separation_gate.py:112:            WHERE regime_scope = 'cross_sectional'
scripts/analysis/phase144_regime_separation_gate.py:126:            f"Zero feature_ic_scores rows found with regime_scope='cross_sectional' and a "
scripts/analysis/phase144_regime_separation_gate.py:146:    regime_scope: str,
scripts/analysis/phase144_regime_separation_gate.py:152:    where = ["symbol = %(symbol)s", "regime_scope = %(regime_scope)s", "is_pooled = %(is_pooled)s"]
scripts/analysis/phase144_regime_separation_gate.py:155:        "regime_scope": regime_scope,
scripts/analysis/phase144_regime_separation_gate.py:323:        regime_scope="symbol_hmm",
scripts/analysis/phase144_regime_separation_gate.py:331:        regime_scope="cross_sectional",
scripts/analysis/phase144_regime_separation_gate.py:341:    _print_side_table("TLT per-symbol HMM (regime_scope=symbol_hmm)", tlt_spreads)
scripts/analysis/phase144_regime_separation_gate.py:342:    _print_side_table("rates cross-sectional (regime_scope=cross_sectional, POOLED)", rates_spreads)
scripts/analysis/equity_regime_separation_gate.py:28:regime_scope='symbol_hmm' for an equity symbol -- confirmed zero as of 2026-07-21 (todo 167),
scripts/analysis/equity_regime_separation_gate.py:120:            WHERE regime_scope = 'symbol_hmm' AND symbol = ANY(%(symbols)s)
scripts/analysis/equity_regime_separation_gate.py:128:            f"Zero feature_ic_scores rows found with regime_scope='symbol_hmm' for any of "
scripts/analysis/equity_regime_separation_gate.py:148:    regime_scope: str,
scripts/analysis/equity_regime_separation_gate.py:153:    where = ["symbol = %(symbol)s", "regime_scope = %(regime_scope)s", "is_pooled = %(is_pooled)s"]
scripts/analysis/equity_regime_separation_gate.py:156:        "regime_scope": regime_scope,
scripts/analysis/equity_regime_separation_gate.py:305:            conn, symbol=symbol, regime_scope="symbol_hmm", is_pooled=False, regimes=None, tfs=tfs
scripts/analysis/equity_regime_separation_gate.py:319:        regime_scope="cross_sectional",
scripts/analysis/equity_regime_separation_gate.py:329:    print("\nequity cross-sectional (regime_scope=cross_sectional, POOLED):")
scripts/ops/alpha/ops_ic_null_calibration.py:17:rationale, including why `is_pooled` (not `regime_scope`) is the correct
scripts/ops/alpha/ops_ic_null_calibration.py:18:stratification axis (`regime_scope='symbol_hmm'` has zero rows today).
scripts/ops/alpha/ops_ensemble_ic_diagnosis.py:75:            # regime_scope may be absent if Phase 141.1 (RSCOPE-01) has not been applied
scripts/ops/alpha/ops_ensemble_ic_diagnosis.py:78:            has_regime_scope = await conn.fetchval(
scripts/ops/alpha/ops_ensemble_ic_diagnosis.py:80:                "WHERE table_name = 'feature_ic_scores' AND column_name = 'regime_scope')"
scripts/ops/alpha/ops_ensemble_ic_diagnosis.py:103:            if has_regime_scope:
scripts/ops/alpha/ops_ensemble_ic_diagnosis.py:106:                    "WHERE ic_ci_lower > 0 AND regime_scope = 'cross_sectional'"
scripts/ops/alpha/ops_ensemble_ic_diagnosis.py:156:        if not has_regime_scope:
scripts/ops/alpha/ops_ensemble_ic_diagnosis.py:158:                "> Note: feature_ic_scores.regime_scope not present on this DB — the "
scripts/analysis/statistical_factor_residual_stage3_ic_falsification.py:38:     (matches feature_ic_scores' is_pooled=true, regime_scope='pooled')
scripts/analysis/statistical_factor_residual_stage3_ic_falsification.py:40:     pooled across days (matches regime_scope='cross_sectional')
scripts/analysis/statistical_factor_residual_stage3_ic_falsification.py:45:   feature_ic_scores itself uses (separate regime_scope rows, not FDR-corrected against
scripts/analysis/statistical_factor_residual_stage3_ic_falsification.py:159:            SELECT regime_scope, count(*), avg(ic_value), avg(ic_ci_lower), avg(ic_ci_upper)
scripts/analysis/statistical_factor_residual_stage3_ic_falsification.py:166:            GROUP BY regime_scope
scripts/analysis/statistical_factor_residual_stage3_ic_falsification.py:175:    for regime_scope, n, avg_ic, avg_lo, avg_hi in rows:
scripts/analysis/statistical_factor_residual_stage3_ic_falsification.py:177:            f"  regime_scope={regime_scope}: n_cells={n} avg_ic={avg_ic:.4f} "
services/ic_engine.py:243:def _resolve_regime_scope(is_pooled: bool, cross_sectional: bool) -> str:
services/ic_engine.py:371:        regime_label_source, computed_at, cluster_id, feature_status_at_eval, regime_scope,
services/ic_engine.py:382:        %(feature_status_at_eval)s, %(regime_scope)s,
services/ic_engine.py:622:    # symbol. Purely additive (new regime_scope='symbol_hmm' rows only), unlike
services/ic_engine.py:943:        # regime/regime_scope columns -- see _compute_symbol_tf's mr_dict docstring.
services/ic_engine.py:976:        # (new regime_scope='symbol_hmm' rows appear/disappear), the same class of
services/ic_engine.py:1554:# regime_scope, training_window_end) -- never a bare training_window_end filter,
services/ic_engine.py:1563:      AND regime_scope = %(pass_type)s
services/ic_engine.py:1571:# valid rows at the same (tf, regime_scope, training_window_end).
services/ic_engine.py:1576:      AND regime_scope = 'cross_sectional'
services/ic_engine.py:1601:        ic_sortino, ic_win_rate, cluster_id, feature_status_at_eval, ic_sharpe_hac, regime_scope,
services/ic_engine.py:1613:        fis.feature_status_at_eval, fis.ic_sharpe_hac, fis.regime_scope, fis.ic_shrunk,
services/ic_engine.py:1626:      AND fis.regime_scope = %(pass_type)s
services/ic_engine.py:1638:        ic_sortino, ic_win_rate, cluster_id, feature_status_at_eval, ic_sharpe_hac, regime_scope,
services/ic_engine.py:1650:        fis.feature_status_at_eval, fis.ic_sharpe_hac, fis.regime_scope, fis.ic_shrunk,
services/ic_engine.py:1663:      AND fis.regime_scope = 'cross_sectional'
services/ic_engine.py:2356:    resolved_regime_scope: str,
services/ic_engine.py:2377:    second label source under a different regime_scope tag.
services/ic_engine.py:2379:    resolved_regime_scope is passed in explicitly (not recomputed via
services/ic_engine.py:2380:    _resolve_regime_scope(is_pooled, cross_sectional) internally) since a caller now
services/ic_engine.py:2681:                    "regime_scope": resolved_regime_scope,
services/ic_engine.py:2730:    resolved_regime_scope: str,
services/ic_engine.py:2797:    regime/regime_scope matching whatever pass this call belongs to (same
services/ic_engine.py:3079:                    "regime_scope": resolved_regime_scope,
services/ic_engine.py:3139:    Grouping key is (regime, is_pooled, regime_scope) -- NOT just (regime,
services/ic_engine.py:3144:    emission and mis-attribute the combined count to whichever regime_scope
services/ic_engine.py:3150:    distinct_cells = {(r["regime"], r["is_pooled"], r["regime_scope"]) for r in all_results}
services/ic_engine.py:3152:    for regime_label, is_pooled, regime_scope in distinct_cells:
services/ic_engine.py:3158:            and r["regime_scope"] == regime_scope
services/ic_engine.py:3166:            "regime_scope": regime_scope,
services/ic_engine.py:3418:        # cross_sectional feeds _resolve_regime_scope for every non-pooled row this
services/ic_engine.py:3448:            _resolve_regime_scope(True, cross_sectional),
services/ic_engine.py:3466:        # mask, resolved_regime_scope) contract as the ordinary cell call directly
services/ic_engine.py:3473:            _resolve_regime_scope(True, cross_sectional),
services/ic_engine.py:3511:            _resolve_regime_scope(False, cross_sectional),
services/ic_engine.py:3623:        # _group_cells_for_metrics groups on (regime, is_pooled, regime_scope)
services/ic_engine.py:4067:                    "regime_scope": "cross_sectional",
services/ic_engine.py:4159:    regime_scope='cross_sectional' (folds into the EXISTING pass_type=
services/ic_engine.py:4160:    'cross_sectional' fingerprint row -- no new pass_type, no new regime_scope,
services/ic_engine.py:4456:                    "regime_scope": "cross_sectional",
scripts/analysis/feature_library_dimensionality.py:140:    regime_scope='cross_sectional'). Pre-registered dedupe: equal-weight mean across
scripts/analysis/feature_library_dimensionality.py:149:              AND regime_scope = 'cross_sectional'
scripts/ops/corpus/ops_ic_fingerprint_equivalence.py:77:# beyond that migration (ic_shrunk/regime_scope/partial_ic/etc. added by later phases;
scripts/ops/corpus/ops_ic_fingerprint_equivalence.py:106:    "regime_scope",
scripts/ops/corpus/ops_ic_fingerprint_equivalence.py:145:           ic_sharpe_hac, regime_scope, ic_shrunk, shrinkage_weight, partial_ic,
```

Note: `services/ensemble_trainer.py`'s hits above (Task 1 output) and `services/ic_engine.py`'s hits
(plan 176-04's own scope) are shown here for completeness of the verbatim grep record, per the task
instruction to preserve raw output -- they are excluded from the summary table above per the plan's
explicit exclusion of both files.
