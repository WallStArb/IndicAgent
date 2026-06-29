---
phase: 141
reviewers: [codex, antigravity]
reviewed_at: 2026-06-28T21:30:00-04:00
plans_reviewed: [141-PLAN.md, 141-P0-PLAN.md, 141-P1-PLAN.md, 141-P2-PLAN.md]
---

# Cross-AI Plan Review — Phase 141

**Reviewers attempted:** codex (substantive), antigravity (substantive — non-TTY bug fixed 2026-06-28), ollama/qwen3.5:4b (failed — context too long for 4b model)

---

## Codex Review

**Summary**

The phase plan is directionally strong: it correctly sequences the corpus-correction work before IC validation, and it recognizes the important architectural constraints around APR, pooled IC recomputation, and worker isolation. The main weakness is that a few steps are not aligned with the current codebase or the canonical registry names, and there are two high-risk gaps that could make the implementation fail even if the code changes "look right": the BaseBatch JSONB pool fix is specified inconsistently, and the new APR namespace for the equity regime windows conflicts with the existing `alpha.regime.*` keys already in use.

**Strengths**

- The dependency ordering is correct: fix validity issues first, rerun the affected corpus, then validate IC, then consider Phase 142.
- The plan correctly treats the corpus rerun as a gated operation and explicitly says the validation report must be based on the corrected corpus, not the stale one.
- The `BaseBatch` / `alpha_publisher` fix is correctly identified as an atomic cross-file issue, not a piecemeal patch.
- The `equity_regime_model` correction targets the real bias source: global percentile ranking over the full corpus.
- The HMM JIT plan respects the process model by keeping DB work out of workers and using worker initialization for warmup.
- The IC validation section has the right output shape: top features, TF breakdown, regime breakdown, demotions, and explicit gate assessment.

**Concerns**

- **HIGH**: The APR namespace for the regime window migration is inconsistent with the codebase. The plan proposes `regime.eq_model.realized_vol_window`, `vix_z_window`, and `ma_window`, but the current service reads `alpha.regime.vix_low_pct`, `alpha.regime.vix_high_pct`, `alpha.regime.breadth_bear`, and `alpha.regime.breadth_bull` from the existing registry in `production/migrations/174_market_regimes.sql` and `services/equity_regime_model.py`. Creating a second namespace will violate the single-definition rule and risk the migration being invisible to the running code.
- **HIGH**: The BaseBatch fix is specified two different ways. The overview says to register the codec via `database_manager.create_pool`, but the detailed step says to switch to bare `asyncpg.create_pool`. That second version would bypass the codec registration that exists in `src/core/database_manager.py`, and it would also bypass the pool metrics instrumentation. This is not just wording drift; it changes the correctness of the fix.
- **HIGH**: The HMM JIT plan assumes `numba` is available, but it is not declared in the current dependency list. The only mention is a comment about pandas-ta pinning numba in `requirements.txt`. Adding `import numba` without updating packaging will break runtime and CI.
- **MEDIUM**: The `equity_regime_model` window work is underspecified around TF scaling. The plan mentions `_tf_window()` and asks for exact values like `_tf_window(200, '5m') == 15600`, but the actual steps do not explicitly require a new helper, tests for each supported TF, or behavior for unsupported TFs. That can leave a silent mis-scaling bug in place.
- **MEDIUM**: The partial corpus rerun step is too compressed. It says to truncate the affected tables and rerun the pipeline, but it does not specify exact SQL, rollback behavior, or how to recover if `equity_regime_model` succeeds and `ic_engine` or `ensemble_trainer` fails mid-run. Because this is a destructive rerun, the failure path needs to be as explicit as the happy path.
- **MEDIUM**: The IC validation plan needs stricter query contracts. The `return_type = 'executable_open_to_open'` filter should be repeated in every step so it is hard to omit. The plan also does not say where the Task 7.5 cost calibration constants are persisted, only that they are produced.
- **LOW**: The plan references some file paths as if the modules were under `src/intelligence/`, but the actual services are in `services/`. Clarity issue, not logic issue.

**Suggestions**

- Use the existing `alpha.regime.*` namespace for the equity regime window parameters, or explicitly migrate every consumer to a new namespace in the same phase. Do not split the registry.
- Rewrite P0-T0 so it explicitly adds the APR keys to the same namespace the service already reads, then update `services/equity_regime_model.py` to load them.
- For the BaseBatch fix, make the step read: "replace direct pool creation with `src.core.database_manager.create_pool(...)` so JSONB codecs and pool metrics are preserved."
- Add tests for `_tf_window()` behavior across all supported TFs and for an unsupported-TF guard.
- Expand the corpus rerun step into explicit SQL with a clear failure policy: truncate only the rows intended to replace, verify counts before and after, define what to do if a downstream stage fails.
- In the IC validation phase, add one explicit requirement that every query repeats the executable-return filter and another that the report stores the Task 7.5 calibration constants in a deterministic location.
- Add `numba` to requirements.txt before implementing `src/intelligence/hmm_jit.py`.
- Tighten the HMM JIT test plan to cover both covariance paths used by `regime_writer` and to verify the worker initializer actually warms each subprocess, not just the parent process.

**Risk Assessment: HIGH**

Two high-severity issues can block or invalidate the phase: the APR namespace mismatch for the equity regime windows, and the inconsistent BaseBatch pool fix description. The missing `numba` dependency is also a concrete blocker for the HMM JIT work. If those three are corrected, the rest of the phase looks executable.

---

## Antigravity Review

### Summary

The proposed plans for Phase 141 (Validity Fixes + Corpus Rerun, IC Validation Analysis, and HMM Numba JIT) are technically sound in their computational logic, particularly the use of Numba compilation to resolve the HMM performance bottleneck and the cleanup of double-encoded JSONB database objects. However, there are significant gaps where critical requirements from the high-level Phase 141 roadmap — such as establishing the Out-of-Sample (OOS) boundary, the null model comparison, and enforcing the per-regime observation floor — are completely omitted from the detailed task lists. Additionally, the plans introduce architectural and mathematical risks, including a parallel JIT compiler race condition and potential silent failures in the `bisect`-based causal rank function due to unhandled `NaN` values and tie-handling discrepancies.

### Strengths

- **Causal Rank Correction**: Transitioning from a global `.rank(pct=True)` to a causal expanding rank in `_compute_vix_pct_rank` successfully eliminates a major look-ahead bias that previously contaminated the feature IC metrics.
- **Robust IC Sharpe Metric**: Relying on `ic_sharpe_hac` (HAC-adjusted Sharpe ratio using Newey-West standard errors) ensures that overlapping return structures do not artificially inflate the statistical significance of features.
- **Targeted Bottleneck Optimization**: Adding `alpha_pass_jit` using `@numba.njit(cache=True)` is highly effective for accelerating the HMM forward filter loop, which was a 20+ hour pipeline blocker.
- **Elimination of JSONB Workarounds**: Migrating `BaseBatch` to use `database_manager.create_pool` resolves a major source of technical debt, standardizing serialization and removing error-prone manual `json.dumps()` workarounds from `alpha_publisher.py`.
- **Test-Driven Execution**: Structuring tasks to write failing unit tests before applying changes ensures immediate detection of regression issues.

### Concerns

- **HIGH: Gaps in Core Phase 141 Deliverables** — CORPUS-01 (Feature Audit), CORPUS-02/03 (OOS Holdout + Null Model), CORPUS-06 (Per-Regime Floor), and CORPUS-07 (I7-Feature Mapping) are all missing from the detailed task lists. No migration sets `alpha.validation.oos_start`; no script computes the null model comparison; no code enforces `alpha.ic.min_obs_per_regime`.
- **HIGH: Parallel JIT Write Race Condition** — In P2, `_jit_warmup` is called via the `initializer` argument of `ProcessPoolExecutor`. If cache files do not exist, all N workers starting simultaneously will attempt to compile and write to `__pycache__` at the same time, causing file locks, corruption, or `PermissionError` failures.
- **MEDIUM: Inconsistent Gate Criteria** — The roadmap says if ≥5 features survive globally, proceed with lower `effective_N`. But the P1 exit gate mandates PASS only if every (timeframe, regime) combination has ≥1 qualifying feature. Across 9 cross-sectional regimes including minority regimes, at least one sparse regime will have zero qualifying features, causing a premature halt.
- **MEDIUM: Unhandled NaNs and Ties in `bisect` Causal Rank** — The causal bisect-based expanding rank for `_compute_vix_pct_rank` does not specify handling for NaN values or duplicate ties. NaN values compared within standard lists will break `bisect` sorting invariants. Raw `bisect_left` will systematically bias percentile ranks for duplicate values vs. Pandas' standard `'average'` tie-handling.
- **MEDIUM: Worker-Level Variable Inheritance** — Setting `_rw_module._jit_warmup_k` in the main process to pass K to workers relies on `fork` inheritance. If the multiprocessing start method is `spawn`, workers fail to inherit the modified global, falling back to the default K and triggering redundant recompilations.
- **LOW: Hardcoded Trading Session Hours in `_tf_window`** — Window scaling uses standard US equity hours (6.5h). Works for 58 ETFs but will be wrong if extended to 24-hour assets (crypto, FX).

### Suggestions

1. **Eliminate JIT Race Condition** — Run sequential compile on a tiny dummy array in the main process before instantiating `ProcessPoolExecutor`. Workers then load the cache read-only.
2. **Safe NaN and Tie Handling for Causal Rank** — Add explicit NaN guard and use `(bisect_left + bisect_right + 1) / 2` average rank to match Pandas `'average'` tie behavior.
3. **Integrate OOS Boundary and Null Model Tasks** — Add migration task to write `alpha.validation.oos_start` to `config_state`. Add script task in P1 to compute null model (equal-weight ensemble IC Sharpe) on OOS window and verify >0.1 advantage.
4. **Add Per-Regime Floor Enforcer** — Add `alpha.ic.min_obs_per_regime` to migration 182 and add explicit tasks to filter cells with N_obs < floor in `ic_engine.py` or `ensemble_trainer.py`.
5. **Simplify Warmup** — Remove `_jit_warmup_k`. Numba compiles for generic type signatures so warming up with fixed K=5 covers all dimension sizes.
6. **Align Gate Criteria** — Change the PASS/FAIL gate to evaluate surviving features globally (≥5 total) or on dominant regimes, not minority regimes.

### Risk Assessment: MEDIUM-HIGH

Code changes address the mathematical validity issues (look-ahead bias, JSON serialization). However, the detailed plans do not execute the core validation steps (OOS baseline, observation floor, distribution audit) required to satisfy Phase 141. Without fixing the parallel compilation race and NaN propagation, the pipeline is likely to encounter runtime crashes and silent calculation corruptions. Implementing the suggested safeguards and task additions lowers execution risk to LOW.

---

## Consensus Summary

Both reviewers (Codex, Antigravity) produced substantive output. Ollama/qwen3.5:4b failed — context too long for 4b model.

### Agreed Strengths

- Sequencing is correct: fix validity issues first, rerun corpus, then validate IC
- Corpus rerun correctly gated on corrected code — not run on the stale corpus
- BaseBatch JSONB fix correctly identified as atomic cross-file change (`database_manager.create_pool`)
- Causal expanding rank fix addresses the real look-ahead bias source
- HMM JIT process model is correct (worker initializer for warmup)
- `ic_sharpe_hac` (Newey-West) is the right metric for overlapping returns

### Agreed Concerns (Both Reviewers)

1. **APR namespace consistency (HIGH — Codex)** — P0-T0 proposes `regime.eq_model.*` but service reads `alpha.regime.*`. Use the existing namespace.
2. **BaseBatch description inconsistency (HIGH — Codex)** — Overview text says "bare asyncpg.create_pool" but task body says "database_manager.create_pool". Task body is correct; fix the overview.
3. **numba dependency (HIGH — Codex)** — Not explicitly declared. Verify pandas-ta pulled it in; add to requirements.txt.
4. **JIT race condition (HIGH — Antigravity)** — Parallel worker startup will race to write Numba cache. Pre-compile sequentially in main process before spawning workers.
5. **NaN/tie handling in bisect causal rank (MEDIUM — Antigravity)** — Unhandled NaN breaks sort invariants; raw bisect_left biases ranks vs. Pandas average.
6. **CORPUS-01/02/03/06/07 tasks missing (HIGH — Antigravity)** — OOS boundary, null model, per-regime floor, and I7-feature mapping are not in any plan wave.

### Divergent Views

- Codex focused on APR namespace collision and the TF-window underspecification; Antigravity did not flag these separately but raised the hardcoded session-hour scaling as a LOW risk.
- Antigravity raised the gate criteria inconsistency (global ≥5 vs. per-regime ≥1 requirement); Codex did not address this directly.
- Antigravity raised spawn-vs-fork worker inheritance for `_jit_warmup_k`; Codex did not flag this.
