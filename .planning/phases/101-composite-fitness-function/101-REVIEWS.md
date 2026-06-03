---
phase: 101
reviewers: [gemini, codex, ollama]
reviewed_at: 2026-06-03T00:00:00Z
plans_reviewed: [101-01-PLAN.md, 101-02-PLAN.md, 101-03-PLAN.md, 101-04-PLAN.md, 101-05-PLAN.md, 101-06-PLAN.md]
---

# Cross-AI Plan Review — Phase 101: Composite Fitness Function

---

## Gemini Review

### 1. Summary
The plan provides a robust, modular, and testable foundation for the agent fitness evaluation system. By decoupling metric calculation (pure functions) from stateful orchestration (auditors) and gating logic (stateless classes), the design aligns well with existing IndicAgent architecture. The mathematical approach to dimensions is consistent, and the staged deployment (Foundation → Logic → Integration) correctly manages risk. The primary challenges lie in the statistical robustness of the novelty metric under low signal overlap and the potential rigidity of the stability/variance gates in a live, evolving agent population.

### 2. Strengths
- **Architectural Cleanliness**: Enforcing "pure" calculator functions prevents the typical "DB-in-the-math-module" anti-pattern.
- **Observability**: Inclusion of OTel metrics and proper `job_completed_total` instrumentation for oneshot services.
- **Deployment Strategy**: Wave-based execution minimizes integration surface area and simplifies testing.
- **Gate Logic**: Moving Promotion/Demotion logic to stateless `Gate` classes allows for thorough TDD and consistent evaluation, avoiding "drift" between shadow and promotion logic.
- **Idempotency**: Explicit migration 115 and clear database schema (D-02) minimize state-sync issues.

### 3. Concerns
- **Novelty Metric Robustness (MEDIUM)**: D-12 treats `r=0` for < 20 overlapping signals. This is a "benefit of doubt" that could mask correlated behavior if agents are simply low-volume. If most agents are low-volume, the novelty score may collapse to 1.0 (appearing falsely optimal).
- **Stability/Variance Gate Rigidity (MEDIUM)**: D-14 (`stddev < 0.02` over 3 cycles) and FIT-06 (`stddev >= 0.2` population-wide) are tight constraints. If the market regime shifts rapidly, all agents might become "unstable" simultaneously, effectively freezing the system even if the agents are performing well.
- **Geometric Mean Sensitivity (MEDIUM)**: While it effectively penalizes failure in any single dimension, the geometric mean is highly sensitive to outliers in smaller agent populations. The "zero collapse" behavior is correct for requirements, but should be documented as a potential trap for new agent development.
- **TimescaleDB/Audit Latency (LOW)**: The auditor runs every 60 mins. If population-level novelty computation on 121+ plugins × 23 instruments takes longer than anticipated, it could block the pipeline or result in stale data before the next window starts.

### 4. Suggestions
- **Novelty Metric Refinement**: Add a "Data Sufficiency" weighting to the novelty score. If overlapping signals < 20, don't just set r=0; return a penalty or lower confidence weight rather than treating it as perfect 1.0 novelty.
- **Variance Gate Relaxation**: For FIT-06, consider an adaptive threshold or fallback mode if population count is low (< 10 agents). A variance of 0.2 is quite high for a narrow set of well-calibrated agents.
- **Stability Gate Window**: The 3-cycle stability gate (D-14) is only 3 hours at 60-min cadence. A longer-term EMA of the composite score would be more stable than a hard 3-cycle window.
- **Audit Resource Limits**: Explicitly define batch size for novelty population calculations to avoid memory bloat as `agent_fitness` history grows.

### 5. Risk Assessment: **MEDIUM**
The design is sound, but the Gates (D-14/15/FIT-06) involve threshold hyperparameters that are difficult to tune in simulation. The risk is that the gates become too restrictive during periods of high market volatility (regime changes), causing the system to freeze promotion/demotion decisions and defeating the adaptive swarm purpose. The logic is correct, but the tuning phase after integration will be the bottleneck.

---

## Codex Review

### 1. Summary
The phase is well decomposed: Wave 1 establishes schema/config/metrics, Wave 2 isolates pure mathematical calculators and gates behind tests, and Wave 3 wires the auditor, persistence, shadow promotion logic, variance gate, and systemd cadence. The design mostly respects project constraints: pure calculators avoid DB/settings coupling, DB writes are centralized in auditor-style services, JSONB/datetime expectations are explicit, and the composite fitness rule matches the geometric mean decision. The largest risks are around statistical reliability, FIT-06 variance-vs-stddev terminology, interpretability of the variance gate, small-population novelty behavior, and whether promotion/demotion history semantics are sufficiently defined for real operations.

### 2. Strengths
- Clear dependency ordering: schema/settings first, pure calculators next, orchestration last.
- Good separation of concerns: calculators and gates are pure; `fitness_auditor.py` owns assembly and persistence.
- Geometric mean implementation matches D-04/D-05 and avoids hidden compensation between dimensions.
- Novelty is correctly treated as population-level and computed in a second pass.
- Staleness handling in `shadow_auditor.py` is a good operational guard.
- Requiring deletion of legacy `_should_promote` / `_should_demote` reduces split-brain gate behavior.
- Systemd + OTel requirements are captured, including `job_completed_total`.
- TDD coverage is planned for all core math before DB orchestration.

### 3. Concerns
- **HIGH: FIT-06 variance gate has a variance vs stddev terminology conflict.** The roadmap says composite score variance must be `>= 0.2`, but Plan 06 names `FITNESS_POPULATION_STDDEV` and `_variance_gate` tests with `threshold=0.2`. Variance and standard deviation are not interchangeable. For `[0.1,0.5,0.9,0.2,0.8]`, variance ≈ 0.092 while stddev ≈ 0.304. The plan must explicitly decide which metric is used.
- **HIGH: Composite variance threshold may be mathematically unrealistic for bounded values.** Composite scores are in `[0,1]`; geometric means compress scores. A variance threshold of 0.2 is extreme for bounded values in [0,1]; if the intended metric is stddev, 0.2 is more plausible.
- **HIGH: Accuracy formula is underspecified.** "Bootstrap CI lower bound" does not define confidence level, bootstrap iterations, random seed behavior, or percentile method. The roadmap success criterion 1 also requires Sharpe ratio, win rate, and statistical significance — but Plan 02 only names `accuracy_score` without storing these submetrics separately.
- **HIGH: Plan 01 column count is inconsistent.** D-02 lists 10 named columns (agent_id, evaluated_at, 5 dimension scores, composite_score, n_resolved, promotion_ready, dimensions_jsonb), but Plan 01's must_haves say "11 D-02 columns." Either a column is missing from D-02 or the plan has an off-by-one.
- **HIGH: Regime specificity promotion criterion is ambiguous.** D-14 says "composite > 0.05 in every evaluated regime," but the schema only has one global `composite_score` and one global `regime_score`. Per-regime composite values are presumably in `dimensions_jsonb`, but this must be explicitly specified in Plan 01/05.
- **MEDIUM: Novelty benefit-of-doubt may reward thin-signal agents.** D-12 yields `r=0` below 20 overlap, giving high novelty. This can be gamed or accidentally favor agents with sparse signal coverage.
- **MEDIUM: Pearson correlation on resolved `signal_id` sets may be brittle.** Agents covering different instruments, regimes, or signal types may appear novel for structural reasons rather than useful behavioral diversity.
- **MEDIUM: Calibration score can go negative.** `1 - brier_score_loss` can be below 0 if confidence values are not bounded to [0,1]. The plan should validate/clamp confidence values or explicitly raise.
- **MEDIUM: Efficiency score I7 convention is implicit.** Plan 03 says I7 plugins pass an empty list and get 1.0 "by convention documented in caller" — but the calculator returns None below min_n for empty lists. Plan 06 must handle this branch explicitly.
- **MEDIUM: DemotionGate history shape is undefined.** "Novelty < 0.15 for 2 consecutive cycles" needs exact ordering semantics — does "history" include the current row or only prior rows?
- **MEDIUM: Promotion stability gate (3 rows) is strict.** Requiring exactly 3 history rows with `stddev < 0.02` means at minimum 3 hours after data is available. At 60-min cadence this is functionally reasonable but the "exactly 3" wording is ambiguous — does it mean "at least 3, use latest 3" or literally "fail if history count != 3"?
- **MEDIUM: `promotion_ready` column ownership is unclear.** D-02 includes `promotion_ready` in the schema, but Plan 06 does not specify whether `fitness_auditor` or `shadow_auditor` computes and writes it.
- **LOW: `OnCalendar=*:0/60` may be unusual syntax.** `OnCalendar=hourly` or `OnCalendar=*:00:00` is clearer; if this exact string is required, tests should verify only what the project expects.
- **LOW: No explicit compression policy SQL in Plan 01.** D-01 specifies compression after 7 days; Plan 01 must_haves don't explicitly mention the `add_compression_policy` call.
- **LOW: Metrics typing underspecified in Plan 01.** "6 FITNESS_* OTel metric instruments" should enumerate each name, whether it is a `point_gauge` or `create_counter`, to match the project's OTel conventions.

### 4. Suggestions
- **Resolve FIT-06 terminology before implementation**: Decide whether the gate uses true variance or standard deviation. Given `FITNESS_POPULATION_STDDEV` metric name, define the gate as `population stddev >= 0.2` and update the roadmap wording accordingly.
- **Add explicit JSONB structure definition**: Plan 01 or Plan 06 should define the exact shape of `dimensions_jsonb` — which submetrics, keys, and types. This is the canonical home for per-regime composites (required by D-14), bootstrap CI bounds, Pearson r peer pairs, token medians, and Brier scores.
- **Add calculator-level input validation**: Reject or clamp confidence outside [0,1]; handle NaN/inf in pnl, confidence, tokens, and correlation vectors; define behavior for empty lists, all-zero vectors, and non-positive token ceiling.
- **Clarify history semantics for gates**: Define whether `history` includes the current row, required sort order, behavior with duplicate `evaluated_at`, and behavior when one of the last 3 composites is NULL.
- **Reconcile `promotion_ready` column**: Either compute it in `fitness_auditor` using the same gate logic or remove/defer it; avoid having two services compute different readiness states.
- **Route DB writes through approved base class**: Plan 06 should name the concrete `BaseAuditor`/writer subclass path for `fitness_auditor`, consistent with the DAG invariant.

### 5. Risk Assessment: **MEDIUM-HIGH**
The architectural decomposition is solid and the pure-function/testing strategy lowers implementation risk. The higher risk comes from metric semantics: FIT-06 variance vs stddev ambiguity, sparse-population novelty behavior, missing submetric storage for roadmap success criteria, and unclear per-regime promotion logic. If those are clarified before Wave 3, implementation risk drops to MEDIUM.

---

## Ollama Review (qwen3.5:4b — reasoning trace)

*Note: Ollama's qwen3.5:4b model returned its output as an internal reasoning trace rather than a formatted response. Key findings are preserved below.*

### Summary
The designs follow a standard monitoring + feedback loop for AI agents. The wave-based decomposition (foundation → calculators → integration) is sound. The main risks are statistical fragility (Pearson correlation on small populations, geometric mean zero-collapse), ambiguous "exactly 3 history rows" semantics in PromotionGate, and potential resource spikes from `fitness_auditor` doing full ledger scans hourly.

### Strengths
- Correct geometric mean implementation: `math.prod` with zero yields 0.0, matching D-04 zero-collapse intent.
- DB schema (Plan 01) is solid as a foundation.
- Stateless gate classes (Plan 05) cleanly separate business logic.
- `OnCalendar=*:0/60` (hourly) is appropriate for the 60-min cadence design.

### Concerns
- **MEDIUM: "Exactly 3 history rows" is ambiguous.** Plan 05 says `PromotionGate` requires "exactly 3 history rows." If the agent has 30 rows of history, does it fail? Almost certainly the intent is "at least 3, use latest 3," but the wording is dangerous if implemented literally.
- **MEDIUM: Pearson r on small populations is statistically unreliable.** At the initial deployment where agent populations are small (< 10), pairwise Pearson r will have high variance, making novelty scores noisy.
- **HIGH: Full ledger scan in fitness_auditor is a resource risk.** `fitness_auditor` reads `signal_ledger_full + llm_calls` with no retention policy on agent_fitness. As history grows, hourly full scans will spike resources. Plan 06 should define a lookback window for the signal reads (e.g., rolling 90 days).
- **MEDIUM: Chicken-and-egg for first deploy.** Agents need resolved signals in `signal_ledger` to clear min_n gates. New agents start with zero history — they will all have NULL composite for the first N cycles, meaning shadow_auditor can make no decisions. This is by design (D-05) but should be documented in the SUMMARY.
- **MEDIUM: Systemd `OnCalendar=*:0/60` ambiguity.** The notation could be interpreted as "every minute" by some systemd versions. `OnCalendar=*:00:00` (every hour at top of hour) or `OnCalendar=hourly` is unambiguous.

### Suggestions
- Change "exactly 3 history rows" to "at least 3, use latest 3" in Plan 05.
- Add a lookback window (e.g., rolling 90d) for `signal_ledger_full` reads in `fitness_auditor` to bound query scope.
- Use `OnCalendar=hourly` for clarity in the timer unit.
- Document the NULL composite cold-start period in the phase SUMMARY so operators are not surprised.

### Risk Assessment: **MEDIUM**
The logic is sound. The main risks are operational (resource load, cold-start period) and wording ambiguities (stability gate history semantics) rather than architectural errors.

---

## Consensus Summary

Three AI reviewers (Gemini, Codex, Ollama) reviewed Phase 101. Codex provided the deepest technical analysis; Gemini focused on operational rigidity; Ollama flagged implementation ambiguities.

### Agreed Strengths

All three reviewers agreed on these strengths:
- **Wave-based dependency ordering** (schema first, pure calculators second, integration third) is clean and reduces risk.
- **Pure calculator functions** (no DB/Settings coupling) is architecturally sound and directly testable.
- **Stateless Gate classes** cleanly separate promotion/demotion logic, enabling TDD without DB.
- **OTel instrumentation** (`job_completed_total`, `FITNESS_*` metrics) follows project conventions correctly.
- **Geometric mean composite** correctly collapses to 0.0 on any zero dimension and NULL on any None — matches D-04/D-05 intent.
- **Novelty as a population-level second pass** is correctly scoped.
- **Staleness check** in shadow_auditor is a good operational guard against stale fitness scores.

### Agreed Concerns

Concerns raised by 2+ reviewers — highest priority to resolve before implementation:

1. **[HIGH — Codex + Gemini] FIT-06 variance vs stddev ambiguity.** The roadmap says "variance >= 0.2" but the plan uses `FITNESS_POPULATION_STDDEV` and tests threshold=0.2 against stddev. These differ by a factor of ~3–5× for bounded values. Must be resolved before Plan 01 metrics are named. Recommendation: gate on **stddev**, rename roadmap wording.

2. **[HIGH — Codex + Ollama] Full signal ledger scan is a resource risk.** `fitness_auditor` reads `signal_ledger_full + llm_calls` with no retention bound. Add a rolling lookback window (e.g., 90 days) to cap query scope; do not rely on no-retention-policy = full history scan every hour.

3. **[MEDIUM — All three] Novelty metric is fragile at small agent populations.** Pearson r is unreliable at low overlap counts, and the r=0 benefit-of-doubt can produce falsely high novelty for sparse agents. Consider storing overlap count and max-correlated peer in `dimensions_jsonb` for diagnostics.

4. **[MEDIUM — Codex + Ollama] "Exactly 3 history rows" in PromotionGate is ambiguous.** Likely should read "at least 3, use latest 3." The literal implementation of "exactly 3" would permanently block agents that have accumulated more history.

5. **[MEDIUM — All three] Gate thresholds may be too tight.** `stddev < 0.02` (agent stability) combined with `stddev >= 0.2` (population diversity) creates a system that must simultaneously be very stable per-agent AND very diverse across agents. At small populations and 60-min cadence this may freeze the governance loop. Consider documenting expected tuning range.

6. **[MEDIUM — Gemini + Codex] Systemd `OnCalendar=*:0/60` is ambiguous.** Use `OnCalendar=hourly` or `OnCalendar=*:00:00` to avoid misinterpretation.

### Divergent Views

- **Plan 01 column count**: Codex flagged a D-02 column count mismatch (10 columns listed in CONTEXT but Plan 01 says "11"). Gemini and Ollama did not flag this. Verify actual column count against D-02 list before migration runs.
- **Calibration score clamping**: Codex flagged that `1 - brier_score_loss` can go negative for out-of-range confidence values; Gemini and Ollama did not raise this. Add confidence validation in `calibration.py`.
- **`promotion_ready` ownership**: Codex flagged that D-02 includes this column but Plan 06 doesn't specify which service writes it. Worth clarifying before Plan 06 implementation.
- **Accuracy submetric storage**: Codex noted the roadmap success criterion 1 requires Sharpe ratio, win rate, and statistical significance to be stored per agent — but Plan 02 only implements a single normalized `accuracy_score`. This is a potential gap vs roadmap deliverables.

---

*To incorporate feedback into planning: `/gsd-plan-phase 101 --reviews`*
