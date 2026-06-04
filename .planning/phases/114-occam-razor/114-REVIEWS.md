# Cross-AI Review: Phase 114 Occam's Razor

**Date:** 2026-06-04
**Reviewers:** Gemini (gemini-2.5-flash), Codex (gpt-5.5)
**Phase:** 114 - Occam's Razor (Complexity-Aware Model Selection)
**Plans Reviewed:** 114-01, 114-02, 114-03, 114-04

---

## Executive Summary

Both reviewers identified **MEDIUM-HIGH overall risk** for Phase 114. The plans are well-structured and follow Renaissance principles, but critical semantics are under-specified:

1. **Complexity-penalized decision rule** is incomplete — penalty mentioned but not reflected in stated decision logic
2. **Return alignment** between complex and baseline models lacks explicit contract
3. **Registry semantics** for rejected models insufficient (rejection status separate from `is_shadow` needed)
4. **Fail-closed behavior** for missing/insufficient data not fully specified

Both reviewers recommend tightening these contracts before implementation begins.

---

## Gemini Review

### Summary

The proposed plan is well-structured, follows a logical progression, and adheres to the project's core "shadow-first" and "complexity-aware" principles. The phased approach effectively decouples the core logic from integration layers. However, the plan lacks explicit consideration for data drift and cold-start scenarios, which could lead to premature rejections.

### Strengths

- **Modular Decomposition:** Wave-based approach (Registry → Statistics → Integration → E2E) correctly maps to system components
- **Renaissance Alignment:** Explicit focus on complexity-penalized evaluation and shadow-registry integration
- **Comprehensive Observability:** Specific OTel metrics and Grafana dashboarding ensure transparent decision-making
- **Validation Focus:** Building statistical test engine as primary reusable component is correct approach

### Concerns

- **HIGH:** Cold-start data sufficiency — 30 days good target, but new agents may have unreliable bootstrap CI. Plan doesn't specify "insufficient data" handling.
- **MEDIUM:** Dependency on feature store latency — computing baseline returns every 15 minutes across all shadow agents may impose significant I/O burden
- **MEDIUM:** Complexity score definition sensitive to infrastructure jitter (latency/training_time noise)
- **LOW:** Lack of re-evaluation/graduation logic for previously rejected models

### Suggestions

- Add "Insufficient Data" handling with `EVAL_STATE_PENDING` status
- Optimize query patterns — pre-aggregate baseline performance instead of full ledger scans
- Use rolling average for latency/training_time to smooth transient noise
- Use structured reason codes (e.g., `REJECTED_LOW_SHARPE`, `REJECTED_COMPLEXITY`) instead of free-text

### Risk Assessment

**MEDIUM** — Architecturally sound, but operational risk of automated rejection based on noisy infrastructure metrics significant. Implementing suggested normalization and structured reason codes will lower risk.

---

## Codex Review

### Summary

The four plans form a mostly coherent phased implementation. Sequencing is directionally right: baseline infrastructure → statistical evaluator → registry integration → end-to-end wiring. Biggest risk is under-specified critical semantics: exact return stream compared, prediction alignment, complexity penalty effect on decision rule, how insufficient data fails closed, and rejection interaction with shadow/graduation registry.

### Strengths (Across All Plans)

- Clean separation between baseline construction and evaluation logic
- Uses bootstrap CI rather than single noisy Sharpe estimate
- Correctly places rejection state in `shadow_registry`
- Includes required OTel metrics
- Integrates with existing AlphaSwarm graduation loop (not separate scheduler)

### Concerns by Plan

**Plan 114-01 (Baseline Registry)**
- **HIGH:** `BaselineBuilder` protocol not specified deeply enough — needs explicit input schema, label semantics, output format, metadata
- **HIGH:** `LinearBaseline` using `LogisticRegression` implies classification, but phase goal compares Sharpe delta from returns. How do class probabilities become positions/returns?
- **MEDIUM:** Rule baseline could become arbitrary unless tied to existing signal features
- **MEDIUM:** Missing fail-closed behavior for insufficient data, NaNs, zero variance, sklearn convergence failure

**Plan 114-02 (Statistical Test Engine)**
- **HIGH:** Decision rule says `ci_lower > 0 → promote` but requirement says "bootstrap statistical test with complexity penalty." Penalty not reflected in stated rule.
- **HIGH:** Sharpe comparison invalid if returns autocorrelated, sparse, non-stationary. Naive bootstrap may overstate confidence.
- **HIGH:** "Promote" may be wrong action — requirement says reject if baseline wins/ties, not necessarily graduate
- **HIGH:** Need explicit handling for zero volatility, too few samples, missing baseline returns
- **MEDIUM:** Complexity score formula may explode across units unless normalized
- **MEDIUM:** No mention of multiple testing across many shadow agents

**Plan 114-03 (Shadow Registry Integration)**
- **HIGH:** Rejection update sets `is_shadow=TRUE`, but rejected models may already be shadow. Need separate rejection status/terminal state
- **HIGH:** Migration may need additional fields: `occam_decision`, `occam_baseline_id`, `occam_ci_lower`, `occam_ci_upper`, `occam_sharpe_delta`, `occam_rejected_at`
- **HIGH:** `_evaluate_agent_with_occam` combines DB query + Sharpe computation + update — risks becoming hard-to-test
- **MEDIUM:** No explicit idempotency — 15-min loop could repeatedly reject
- **MEDIUM:** No transaction/locking strategy for concurrent graduation and rejection

**Plan 114-04 (End-to-End Integration)**
- **HIGH:** Real baseline return computation too late — statistical test engine needs return construction contract first
- **HIGH:** Complexity columns in `ml_models` also too late if Wave 2 needs real complexity lookup
- **HIGH:** Synthetic integration tests insufficient for system whose core risk is data alignment
- **MEDIUM:** No mention of backfill or default handling for existing `ml_models` rows

### Suggestions (Consolidated)

1. **Define protocol methods explicitly:** `fit(data)`, `predict_positions(data)`, `score_returns(data)`, `metadata()`
2. **Use paired bootstrap over timestamp-aligned return deltas:** `delta_t = complex_return_t - baseline_return_t`
3. **Define penalized decision rule explicitly:** `penalized_delta = sharpe_delta - lambda * log1p(complexity_ratio)`
4. **Treat ties and uncertainty as rejection or continued shadow, not graduation**
5. **Rename outcome states carefully:** `reject_complex`, `retain_shadow`, `eligible_for_graduation_review`
6. **Add explicit registry fields or status enum:** `occam_status`, `occam_rejection_reason`, `occam_last_decision_at`
7. **Make rejection idempotent:** update only if current status still eligible/shadow
8. **Move return-construction and complexity schema into Waves 1-2**
9. **Add golden dataset test** with known model returns, baseline returns, expected Sharpe delta, expected CI behavior
10. **Require complexity metadata present for evaluation** — if absent, fail closed rather than use defaults

### Cross-Plan Risks

- **Statistical decision ambiguity:** Largest gap is exact complexity-penalized decision rule
- **Return alignment:** Complex and baseline models must run on identical 30-day signal data with paired timestamps, instruments, horizons
- **Registry semantics:** "Rejected but still `is_shadow=TRUE`" not enough state to protect graduation loop
- **Fail-closed behavior:** Missing data, insufficient samples, invalid Sharpe, missing complexity metadata must block promotion
- **Dependency ordering:** Real return computation and complexity metadata are foundational, not end-to-end polish

### Risk Assessment

**MEDIUM-HIGH** — Plans well-structured and largely cover success criteria, but current breakdown risks implementing mechanically complete system before core statistical and data contracts nailed. Define return stream, complexity penalty, decision states, and fail-closed behavior before implementation begins.

---

## Consensus Findings

Both reviewers agree on these critical gaps:

| Issue | Severity | Both Reviewers |
|-------|----------|----------------|
| Complexity penalty not in decision rule | HIGH | ✓ |
| Return alignment contract unspecified | HIGH | ✓ |
| Cold-start / insufficient data handling | HIGH | ✓ |
| Registry rejection state insufficient | HIGH | ✓ (Codex) / MEDIUM (Gemini) |
| Complexity columns too late in sequence | HIGH | Codex |
| Metrics cardinality risk | MEDIUM | Codex |
| Infrastructure noise in complexity score | MEDIUM | Gemini |

---

## Recommended Actions

1. **Revise Plan 114-02 Task 4** — explicitly define complexity-penalized decision rule with formula
2. **Revise Plan 114-01 Task 1** — add explicit `BaselineBuilder` protocol with input schema and output format
3. **Add migration task to Plan 114-03** — include additional Occam audit fields (`occam_ci_lower`, `occam_ci_upper`, `occam_sharpe_delta`, etc.)
4. **Move complexity schema to Plan 114-02** — statistical test engine needs real complexity lookup contract
5. **Add explicit "insufficient data" handling** across all plans with `EVAL_STATE_PENDING` status
6. **Add idempotency guard** in Plan 114-03 Task 4 rejection UPDATE
7. **Add golden dataset test** to Plan 114-04 testing section

---

## Conclusion

The phase plans are directionally sound and aligned with Renaissance principles. However, the **statistical decision contract** and **data alignment semantics** need to be specified before implementation begins. Once these contracts are explicit, the wave structure should work well.

**Recommendation:** Re-run `/gsd-plan-phase --reviews` to incorporate these findings before executing the plans.
