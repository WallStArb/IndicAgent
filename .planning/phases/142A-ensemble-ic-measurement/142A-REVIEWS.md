---
phase: 142A
reviewers: [codex]
reviewed_at: 2026-07-02T16:26:18Z
plans_reviewed: [142A-01-PLAN.md, 142A-02-PLAN.md]
---

# Cross-AI Plan Review — Phase 142A

## Codex Review

**Summary**

The phase split is well thought out: Wave 1 cleanly establishes the measurement substrate, Wave 2 adds calibration and gate reporting, and both plans correctly reuse the existing IC methodology rather than re-deriving it. The main risk is not architectural but statistical and operational: a few load-bearing details are still ambiguous or wrong in ways that could make the phase gate confidently misleading, especially around walk-forward stability, run selection, and diagnosis aggregation.

**Strengths**

- The plan is aligned with existing project patterns in `services/ic_engine.py`, `services/ensemble_trainer.py`, and `src/core/agent/base_batch.py`.
- It correctly avoids subclassing or forking the IC engine math and instead composes the existing implementation.
- The 9-label regime namespace is resolved explicitly, which avoids the stale 4-label schema trap.
- The phase is cleanly separated into measurement, calibration, gate evaluation, and diagnosis, which reduces scope coupling.
- The test plan is strong: it includes pure helper tests, grep-style invariant tests, and coverage for the critical APR-binding paths.
- The plan correctly treats OOS contamination as a hard boundary and keeps Phase 142B out of scope.

**Concerns**

- **HIGH**: `142A-01-PLAN.md` Task 2 treats `walk_forward_stable` as a raw fold-IC ratio proxy, but the locked requirement (ROADMAP.md EIC-03) is an IC Sharpe ratio gate. That is not a minor wording issue: fold IC magnitude and fold IC Sharpe can disagree materially, so this can admit unstable signals or reject stable ones.
- **HIGH**: `142A-02-PLAN.md` Task 3 (EIC-05 diagnosis, Section 2) says the pooled-vs-per-symbol comparison computes a "median" but the SQL uses `max(CASE WHEN NOT is_pooled THEN ic_ci_lower END) AS per_symbol_median_ci_lower`. That makes the diagnosis report statistically wrong in the exact place it is supposed to explain regime granularity failures.
- **HIGH**: The idempotency story for `alpha_ensemble_ic` is incomplete. In `142A-01-PLAN.md` the PK is `(event_row_id, scored_at)`, `scored_at` defaults to `now()`, and `event_row_id` deliberately excludes any run timestamp (per Task 2's content_key spec). Unless the service pins one deterministic `scored_at` value that matches a prior run's value, `ON CONFLICT (event_row_id, scored_at)` will never fire in practice — re-runs append new rows instead of updating in place, contradicting the plan's own "true idempotency" claim.
- **MEDIUM**: Both Wave 2 scripts key off `scored_at >= NOW() - INTERVAL '7 days'` instead of selecting a single completed run. That can mix multiple runs, which makes the gate and diagnosis non-deterministic if the job is rerun manually or retried.
- **MEDIUM**: The plan mixes pooled and per-symbol cells into the same BH-FDR correction and gate fraction. That is convenient, but pooled rows answer a different inferential question and usually have very different effective N, so the phase gate can be distorted by pooling behavior rather than signal quality. (Plan 01 Task 2 explicitly flags this as an accepted v1 simplification — worth confirming that's still the intended tradeoff.)
- **MEDIUM**: The engine startup gates validate `alpha_events` and `forward_returns`, but not `market_regimes`. Since the whole regime-stratified measurement depends on that table, a partial or missing regime corpus could degrade silently instead of failing loud.
- **MEDIUM**: EIC-02 calibration excludes only `passes_fdr=false` cells. That is a good first filter, but it still leaves room for low-N cells with positive CI to influence `hold_max_bars`. Given that this writes a load-bearing APR parameter, the plan should be stricter or at least explicitly justify why `reliable` is not part of the calibration gate.
- **LOW**: The diagnosis script's fallback to 200 for `min_obs_per_regime` is operationally convenient, but it can hide APR or migration drift. For a report intended to explain why a gate failed, silent fallback is less desirable than a loud warning.

**Suggestions**

- Make `walk_forward_stable` compute the actual fold IC Sharpe ratio, or if the proxy is retained for v1, get explicit sign-off that the ROADMAP's EIC-03 wording is being knowingly relaxed (the plan already documents the substitution as deliberate — this needs a decision, not a fix).
- Fix the diagnosis query to compute a true median (`percentile_cont(0.5) WITHIN GROUP`) for the per-symbol comparison, not `max(...)`.
- Add an explicit run marker or deterministic `scored_at` value (e.g., truncate to the calendar week at which the job runs) so `alpha_ensemble_ic` upserts are actually idempotent within a run, while still accumulating a real time-series of vintages across runs if that's desired.
- Select the latest completed run explicitly in Wave 2 (`scored_at IN (SELECT max(scored_at) FROM alpha_ensemble_ic)`), rather than using a rolling 7-day window.
- Add a startup prerequisite check for `market_regimes`.
- Consider requiring `reliable=true` or a minimum `n_independent` threshold in EIC-02 calibration, not just in diagnosis.
- Make the diagnosis script fail loud, or at minimum emit a prominent warning, if `min_obs_per_regime` is missing from APR.

**Risk Assessment**

**High.**

The architecture is solid, but the plan still has a few load-bearing statistical and run-selection flaws. The biggest ones are the EIC-03 stability proxy and the diagnosis aggregation bug, both of which can produce a confident but wrong go/no-go signal — precisely the "silent wrong answer" this project's own principles rank as the worst outcome. If those are corrected, the overall risk drops substantially; as written, this is not safe to treat as a low-risk phase gate.

---

## Consensus Summary

Only one external reviewer (Codex) was invoked for this pass — `review.default_reviewers` is configured to `["codex"]` only; Gemini/OpenCode/Qwen/Cursor were not installed, and Claude was skipped for independence (this session runs inside Claude Code). No cross-model consensus was computed; treat this as a single independent review, not a converged verdict.

### Findings independently verified against the live plan text (2026-07-02, this session)

- **EIC-03 Sharpe-vs-ratio substitution** — CONFIRMED. `142A-01-PLAN.md` Task 2 action text explicitly documents this as "a deliberate substitution from the CONTEXT.md 'IC Sharpe ratio' wording, not an oversight." Real divergence from ROADMAP.md's EIC-03 text; already flagged by the plan author but not escalated for a decision.
- **EIC-05 median/max bug** — CONFIRMED. `142A-02-PLAN.md` line 272: `max(CASE WHEN NOT is_pooled THEN ic_ci_lower END) AS per_symbol_median_ci_lower` — column is named "median" but the aggregate is `max()`. Genuine bug.
- **Idempotency gap** — CONFIRMED by inspection. `event_row_id` excludes any run timestamp (Task 2), but `scored_at` (part of the PK) defaults to `now()` with nothing in the plan pinning it to a stable per-run value. `ON CONFLICT (event_row_id, scored_at)` will not collide across separate invocations as currently specified.

### Divergent Views

N/A — single reviewer this pass.
