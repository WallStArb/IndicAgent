---
phase: 138
reviewers: [codex, ollama]
reviewed_at: 2026-06-21T20:00:33Z
plans_reviewed:
  - 138-P1-PLAN.md
  - 138-P2-PLAN.md
  - 138-P3-PLAN.md
  - 138-P4-PLAN.md
  - 138-P5-PLAN.md
note: antigravity skipped (GUI editor, not headless-capable); claude skipped (self-review independence rule)
---

# Cross-AI Plan Review — Phase 138

## Codex Review

**Summary**

The plan has the right overall decomposition: schema/control-plane first, causal labels next, then IC computation, then tests/reporting. The strongest parts are the explicit regime conditioning, the separation of outcome labels from features, and the intent to keep APR-backed knobs centralized. The main problems are not architectural shape but statistical and operational correctness: the proposed HMM labeling is not yet truly causal, the IC validation/bootstrap design is too weak for financial time series, and the service-auditor integration is incomplete for timer-driven oneshots. Those are the kinds of issues that can silently produce wrong answers.

**Strengths**

- Good wave ordering and dependency structure: schema/APR before writers, writers before IC, IC before report.
- Strong causal intent in the outcome layer: forward labels are separated from feature computation instead of being mixed into the feature table.
- Regime-stratified IC is the right idea; pooled-only IC would absolutely hide sign flips.
- Good instinct to keep thresholds in APR and derive feature names from the dataclass instead of hardcoding 54 strings.
- The plan is explicit about D-06, OTel, idempotency, and walk-forward, which is the right operational bar.
- Using a report artifact for Phase 139 is the right bridge between research and ensemble construction.

**Concerns**

- **HIGH:** Plan 2 is not actually causal as written. `hmmlearn.GaussianHMM.predict()` on the full sequence uses the whole path, so it leaks future information even if you avoid a smoothed backward pass. The current repo already has a forward-only HMM path that is the right reference model: `src/intelligence/feature_cache.py` (lines 117, 345) and the forward recursion in `src/intelligence/features/smc_context/hmm_regime.py` (line 391). The plan should mirror that causal filter, not Viterbi over a completed history.
- **HIGH:** Plan 2 references `feature_vectors.close`, but the physical schema does not contain a close column. `feature_vectors` contains the 54 feature fields plus metadata — no raw OHLCV. The regime writer needs to read raw bars from `market_data_ohlcv`, not the feature table.
- **HIGH:** Plan 1 omits the service-auditor oneshot handling. New timer-driven services will be discovered by `service_auditor`, and anything not in `_ONESHOT_UNITS` can be treated as a dead service and restarted. The auditor explicitly skips only units in `_ONESHOT_UNITS` (lines ~94 and ~506 in `services/service_auditor.py`). Registering in `_DAG_ORDER` alone is not enough.
- **HIGH:** The `feature_ic_scores` key design is inconsistent. The plan says "one row per (feature, symbol, tf, regime, lookahead)" but also includes `training_window_end` in the PK and fold-related columns in the same row. This mixes fold detail with aggregate summary and makes dedup semantics unclear. Either a fold-detail table + summary table, or a single table with explicit `fold_id` and a separate summary materialization, is cleaner.
- **HIGH:** The NULL-regime partial unique index conflates two different states: pooled rows and unlabeled/missing-regime rows. This is dangerous for both `ON CONFLICT` behavior and data interpretation. A dedicated `regime_scope`/`is_pooled` column or a generated coalesced key is safer.
- **MEDIUM:** The bootstrap plan is too weak for time series. Plain iid bootstrap on bar data understates uncertainty. The repo already uses circular block bootstrap for a similar statistical promotion job in `production/scripts/batch_agent_memory.py` (line ~569). That is the correct pattern to reuse.
- **MEDIUM:** The walk-forward design needs a purge/embargo around the lookahead horizon. Without it, train/test boundaries leak through overlapping forward-return labels, especially with 20/60-bar targets.
- **MEDIUM:** Null and constant-column handling for Spearman IC is unspecified. Constant features or near-constant regime slices are guaranteed to appear, and `spearmanr`/rank correlation will return NaN or unstable p-values. An explicit skip/count policy is required.
- **LOW:** Plan 1's `alpha.` prefix change is redundant — `ConfigService.OPS_PREFIXES` already includes `alpha.` at `src/config/config_service.py:39`. No code change needed.
- **LOW:** The discovery report should be machine-readable as well as markdown. For Phase 139 feature selection a CSV/JSON artifact will be more useful.

**Suggestions**

- Replace Plan 2's `predict()`-based labeling with an explicit forward-filter implementation aligned to the existing causal HMM code path. Keep parameter fitting separate from online labeling.
- Add a canonical regime snapshot/version field if regimes remain mutable, or write regimes to an append-only label table so historical IC never changes after the fact.
- Introduce an explicit pooled-regime discriminator instead of using NULL to mean "pooled."
- Split IC persistence into fold-level detail and aggregate summary.
- Use circular block bootstrap for confidence intervals and a purged/embargoed walk-forward split.
- Add a hard runtime gate that refuses to proceed if `feature_vectors`, `outcome_labels`, or regime coverage are empty below threshold.
- Make new oneshot services first-class in `service_auditor`: add to `_ONESHOT_UNITS` and verify inactive timer jobs are skipped not restarted.
- Emit `job_completed_total{job,status}` and flush OTel in `finally` blocks, so failure paths still export the exit signal.
- Expand the IC discovery artifact to include fold-level IC, sample counts, sign stability, and effective-N by regime/TF/lookahead; export a CSV/JSON companion.
- Add tests for off-by-one outcome labeling, gap handling, constant-feature IC cases, and the regime writer's causal semantics.

**Risk Assessment:** HIGH — Multiple paths to silent statistical error: non-causal regime labeling, weak bootstrap methodology, ambiguous pooled-vs-null regime handling, incomplete service-auditor treatment.

---

## Ollama Review (nemotron-3-nano:4b)

**Summary**

The Phase 138 plan demonstrates solid architectural foundations but introduces several statistical correctness gaps that could jeopardize the "silent wrong answer" invariant. Causal labeling, regime stratification, and walk-forward validation are largely in place, yet edge-case handling (empty inputs, duplicate timestamps) and performance-critical bottlenecks (scalable bootstrap CI, BH-FDR batch processing) are insufficiently enforced. The DAG remains clear, but APR compliance for numeric gates is incomplete and the report may be too technical for Phase 139 ensemble use.

**Strengths**

- Table schema isolates causal outcome labels with complete backward flags.
- APR-driven constant seeding removes domain-hardcoded thresholds.
- Partial unique index for NULL regime enables safe merge without conflict (though see concerns).
- Bootstrapped HMMTrainer reuse limits duplication.
- Fully vectorized Spearman rank correlation eliminates per-cell loops.
- Manual bootstrap CI is auditable step-by-step.
- BH-FDR applied per (symbol, tf) batch preserves original order.
- Unit tests validate statistical correctness and causal intent.
- Idempotency test confirms safe batch re-run.

**Concerns**

- **HIGH:** Silent crash on empty inputs (Plans 1, 4) — violates "crash loud > silent" invariant.
- **HIGH:** Missing edge-case validation for bootstrap CI, HMM, BH-FDR ordering (Plans 2-4).
- **HIGH:** Potential data leakage via future-gap rows in outcome builder if no WHERE clause gates bar_ts <= TRAINING_WINDOW_END (Plan 3).
- **HIGH:** BH-FDR batch processing must maintain parallel order with cell tuples — if implementation drifts, q-values corrupt downstream IC rows.
- **HIGH:** IC Sharpe gate under-exposed for rare instruments/TFs below 20K obs threshold.
- **MEDIUM:** NULL regime handling relies on partial unique index but batch UPDATE may still write NAs; downstream IC may inherit NAs.
- **MEDIUM:** GaussianHMM assumes normal returns; market regimes can be heavy-tailed — may produce poor regime separation.
- **MEDIUM:** Runtime risk if hmmlearn fails on empty observation matrix; silent fallback not defined.
- **MEDIUM:** JOIN gate only on feature_vectors bar_ts; missing bar rows could cause inconsistencies.
- **LOW:** Test tolerance `1e-10` for vectorized IC vs scipy may surface numpy rounding differences.
- **LOW:** Report generation in plain markdown lacks automated diff detection if APR parameters change.

**Suggestions**

- Implement pre-run validation that raises RuntimeError on < 500 obs per symbol/tf (APR-gated threshold).
- Wrap migrations in atomic DB transactions; document rollback steps.
- Guard HMM construction with early return if NaN count > 5% or matrix size < n_components * minimum.
- Add WHERE bar_ts <= TRAINING_WINDOW_END to outcome_writer to avoid future-gap rows.
- Insert runtime check: `if n_independent < min_reliable_n: continue` — documented in logs.
- Add a metric indicating walk-forward validation coverage rate across regimes.
- Enforce APR-backed numeric gates (min_obs, min_reliable_n, Sharpe floor) with runtime checks.
- Implement a causal-integrity checker before insertion that throws RuntimeError if any lookahead logic breached.
- Design scalable pipeline: batch inference of all (symbol, tf, regime, lookahead) combos in memory-efficient chunks.

**Risk Assessment:** HIGH — Several high-severity points jeopardize the invariant and may propagate to Phase 139, causing ensemble selection artifacts or data-leakage.

---

## Consensus Summary

Both reviewers independently rated Phase 138 as **HIGH RISK**. The architectural decomposition and wave ordering are sound. The risk is concentrated in statistical correctness and operational safety.

### Agreed Strengths

- Wave ordering is correct: schema → regime labeler → outcome writer → IC engine → tests. Clean DAG.
- Separating `outcome_labels` from `feature_vectors` is the right SoC decision.
- Regime-stratified IC (not pooled) is non-negotiable and the plan enforces this.
- APR-backed thresholds + FeatureVector-derived feature names are the right design.
- D-06, OTel, idempotency, walk-forward: all explicitly scoped. Right operational bar.

### Agreed Concerns (Raised by Both Reviewers)

1. **[HIGH] HMM labeling is not causal.** `GaussianHMM.predict()` on the full history leaks future information even without a backward smoother — Viterbi over the complete sequence is not causal. Plan 2 must use the forward-filter (alpha-pass only) HMM path that already exists in the codebase (`src/intelligence/features/smc_context/hmm_regime.py:391`).

2. **[HIGH] feature_vectors has no OHLCV columns.** Plan 2 references `feature_vectors.close` which does not exist. The observation matrix for HMM must be built from `market_data_ohlcv`, not the feature table.

3. **[HIGH] Empty-input guards are comments, not code.** Both reviewers flag that "blocked prerequisite" notes are insufficient. The ICEngine must raise `RuntimeError` at startup if `feature_vectors`, `outcome_labels`, or regime coverage fall below threshold — not just log a warning and continue.

4. **[HIGH] NULL regime is overloaded.** Using `NULL` to mean both "pooled" and "regime unknown/missing" is ambiguous for `ON CONFLICT` semantics and data interpretation. Both reviewers independently flag this as a correctness risk.

5. **[MEDIUM-HIGH] Bootstrap is iid, not block.** Financial bar data has autocorrelation. A plain iid bootstrap understates CI width and will make features look more reliable than they are. Circular block bootstrap (already in the codebase) is the correct pattern.

6. **[MEDIUM] Walk-forward needs purge/embargo.** Without a gap between train and test windows equal to the lookahead horizon (60 bars max), forward-return labels from the training set overlap with the test window.

7. **[MEDIUM] Constant/degenerate feature handling is unspecified.** Near-constant features and thin regime slices will produce NaN Spearman values. An explicit skip policy with metric emission is required.

### Divergent Views

- **service_auditor `_ONESHOT_UNITS`** (codex only): Codex identified that the three new oneshots need entries in `_ONESHOT_UNITS`, not just `_DAG_ORDER`, to avoid being treated as dead daemons. Ollama did not raise this — but the codex finding is verifiable at lines ~94/506 of `services/service_auditor.py`.
- **feature_ic_scores schema mixing fold detail + summary** (codex only): Codex argues `training_window_end` in the PK combined with fold columns is a schema smell. This is worth investigating — if `wf_fold_count`/`wf_pass_count` are summary aggregates and `training_window_end` is the dedup key, the schema is arguably fine. But if fold-level rows are needed later, a separate table is cleaner.
- **Report machine-readability** (both, different emphasis): Both agree markdown alone is insufficient for Phase 139 automation, though neither specifies the exact format. A JSON sidecar with the passing-feature list is the minimum.
