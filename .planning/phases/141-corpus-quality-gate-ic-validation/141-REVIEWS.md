---
phase: 141
reviewers: [codex]
reviewed_at: 2026-06-28T21:30:00-04:00
plans_reviewed: [141-PLAN.md, 141-P0-PLAN.md, 141-P1-PLAN.md, 141-P2-PLAN.md]
---

# Cross-AI Plan Review — Phase 141

**Reviewers attempted:** codex (substantive), antigravity (failed — returned only stdin path, likely non-TTY drop), ollama/qwen3.5:4b (failed — context too long for 4b model)

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

## Consensus Summary

Only one reviewer (Codex) produced substantive output. Antigravity returned a non-TTY stdin path (known bug). Ollama/qwen3.5:4b returned empty (context too long for 4b model).

### Agreed Strengths (Codex)

- Sequencing is correct: fix first, rerun, then validate
- Corpus rerun correctly gated on corrected code
- BaseBatch fix correctly identified as atomic cross-file change
- HMM JIT process model is correct (worker initializer, not main-process warmup)
- IC validation output shape is correct

### Top Concerns to Address Before Execution

1. **APR namespace (HIGH)** — P0-T0 proposes `regime.eq_model.*` but the service already uses `alpha.regime.*`. Verify the correct namespace by checking what `equity_regime_model.py` actually reads, and keep all keys in the same namespace family.
2. **BaseBatch description inconsistency (HIGH)** — The P0-T1 step text says "switch to bare asyncpg.create_pool" in the overview but the task body is correct ("replace with `database_manager.create_pool`"). Confirm the task body is authoritative — the overview wording is wrong.
3. **numba dependency (HIGH)** — Check whether `numba` is already installed (pandas-ta may have pulled it in). If installed: add it explicitly to requirements.txt. If not installed: install it first in P2-T1.

### Divergent Views

N/A — single reviewer.
