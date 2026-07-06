---
phase: 143
reviewers: [codex]
reviewed_at: 2026-07-06T00:00:00Z
plans_reviewed: [143-01-PLAN.md, 143-02-PLAN.md, 143-03-PLAN.md]
---

# Cross-AI Plan Review — Phase 143

Only `codex` was invoked, per `review.default_reviewers: ["codex"]` in `.planning/config.json`.
`agy` (Antigravity) and `coderabbit` are also installed but were not in scope for this run since no
`--all` or explicit reviewer flags were passed. `claude` was skipped for reviewer independence
(the orchestrating session is itself Claude Code).

## Codex Review

**Summary**

Overall, the three-wave structure is strong: Plan 01 establishes label quality first, Plan 02 gives the batch job a synchronous and transactional state-machine write path, and Plan 03 centralizes all lifecycle decisions in the existing `ic_engine` post-run boundary with no new daemon. The main weakness is that the load-bearing part of the phase is still under-specified where it matters most: Plan 03 does not cleanly define feature-level versus cell-level transition semantics, and the promotion/weight restoration path is not fully pinned down. Those gaps create correctness risk even if the migrations and code compile.

**143-01-PLAN.md**

Strengths
- Good ordering: it correctly ships the HMM label trustworthiness gate before any downstream lifecycle routing.
- The scope is appropriately narrow: P2b/P2c only, with P3 explicitly deferred to manual calibration.
- The APR-backed config approach is consistent with the project's threshold governance rules.
- The `hmm_churn` feature is tied directly to the already-computed smoothed labels, which matches the intended data provenance.

Concerns
- MEDIUM: The plan does not fully specify behavior for edge cases like empty series, single-bar series, or non-converged fits before the occupation gate runs.
- MEDIUM: Changing the `update_rows` tuple shape is a contract break. The plan says to keep it consistent, but it does not call out every downstream consumer that must be adjusted or tested.
- LOW: The plan says the degenerate model returns an empty write set, but it could be clearer whether the caller should still emit a run-level diagnostic or merely a warning.
- LOW: The "manual-only" P3 deferral is correct, but the plan should explicitly state that defaults remain in force until the later calibration pass lands.

Suggestions
- Add explicit skip behavior for zero-length/degenerate inputs and convergence failures.
- Add a regression test for the smallest possible valid sequence, not just a healthy and a degenerate one.
- State the postcondition for a skipped write more explicitly: no DB write, warning emitted, caller receives a deterministic marker.

Risk assessment
- **LOW to MEDIUM.** The implementation is straightforward and well bounded, with limited blast radius.

**143-02-PLAN.md**

Strengths
- The sync `psycopg2` write path is the right design for `ic_engine`; it avoids the async/event-loop mismatch the research uncovered.
- The plan correctly keeps the authoritative state machine in `feature_registry` rather than inventing a parallel lifecycle table.
- It cleanly reuses the existing `alpha.decay.recovery_min_observations` key instead of duplicating it.
- The "deprecated is operator-only" rule is explicit, which prevents accidental automated escalation into a terminal state.
- Dropping the dead `feature_ic_scores` columns is aligned with the research findings and avoids perpetuating unread schema.

Concerns
- HIGH: Atomicity is not fully nailed down. The plan talks about a sync writer plus a sibling helper for counter updates, but it does not require a single transactional unit for status change, counter mutation, and `pre_shadow_weight` persistence. That can create drift.
- HIGH: The plan says promotion should restore `pre_shadow_weight`, but it does not specify the actual persistence target or mechanism for restoring the operational weight. That is a functional gap, not just an implementation detail.
- HIGH: Cache coherency is under-specified. If the hook mutates status and counters in one run, the plan does not define when the in-memory registry cache must be refreshed relative to subsequent eligibility checks.
- MEDIUM: The operator-only `deprecated` path is enforced, but the plan does not define how manual/operator transitions are handled or tested. That may leave a legitimate workflow unverified.
- LOW: Dropping the dead columns is fine per research, but it would be prudent to explicitly check for any ad hoc SQL or BI dependencies before removal.

Suggestions
- Make one method or one explicit transaction own all lifecycle mutations for a feature: status, counters, and weight capture/restore.
- Define where `pre_shadow_weight` is read from and where the restored weight is written.
- Add a cache refresh rule after successful transition writes, or make the sync method return the updated record state.
- Add one test for the operator-only `deprecated` path so the manual workflow is documented, not just the automated rejection.

Risk assessment
- **MEDIUM to HIGH.** The plan is directionally correct, but the transaction boundary and weight-restoration semantics need to be sharper before execution.

**143-03-PLAN.md**

Strengths
- The no-daemon, end-of-run hook design is the right architectural choice for this phase.
- Regime-shift guarding first is correct and reduces the chance of mass-zeroing due to HMM artifacts.
- The plan reuses the existing active-only ensemble filter as a regression lock, which is efficient and low risk.
- The observability additions are minimal and appropriate: one fact table plus a small set of OTel metrics.
- The staleness alert is scoped as a gauge/alert, not a new service, which keeps the phase bounded.

Concerns
- HIGH: The biggest gap is semantic ambiguity between feature-level and cell-level routing. The plan talks about active cells, features, and feature-regime cells interchangeably, but it never states the exact aggregation rule that decides when a feature is demoted or promoted.
- HIGH: Promotion weight restoration is still not fully specified. The plan says to restore `pre_shadow_weight`, but it does not define the exact write path or whether a separate ensemble-weight update is required.
- HIGH: Idempotency/retry behavior is not defined. If the hook partially succeeds and is rerun, the plan does not say how to prevent duplicate `integrity_monitor` rows or repeated transitions beyond "status already changed."
- MEDIUM: The prior-run timestamp logic for staleness is underspecified if manifest metadata is missing, incomplete, or the prior run failed late.
- MEDIUM: The hook reads and processes per-run facts in-process. That is fine for this scale if the run set is small, but the plan should at least acknowledge query cardinality and indexing requirements for the weekly corpus.
- LOW: The diagnostics SQL file is useful, but the plan should be clear that it is supporting material, not the primary source of truth for lifecycle state.

Suggestions
- Define the transition unit explicitly: per feature, per TF, or per feature-regime cell. Right now that is the main correctness risk.
- Make the hook idempotent by keying facts on `training_window_end` and/or a run identifier from the manifest.
- Specify the exact persistence mechanism for restored weights.
- Add a fallback rule for staleness timestamp derivation when the manifest is incomplete.
- Add a note about expected row counts and indexing for the per-run IC fact query so performance does not become an afterthought.

Risk assessment
- **HIGH.** This is the critical path of the phase, and it still contains correctness ambiguities that could cause wrong transitions even if all tests pass.

**Overall**

- **Overall risk: HIGH.**
- The phase sequencing is good and the plans are much better than a typical "build everything" draft.
- The main risk is not scope creep; it is underspecified lifecycle semantics in Plan 03 and, to a lesser extent, transactional completeness in Plan 02.
- If you tighten the feature-vs-cell aggregation rule, weight restoration path, and idempotency model, the phase becomes materially safer.

---

## Independent Verification (orchestrating session, before writing this file)

Codex's two most severe findings were checked directly against the live schema rather than taken at
face value:

1. **Feature-vs-cell granularity mismatch — CONFIRMED.** `feature_registry.feature_name` is the
   sole PRIMARY KEY (migration 172) — one row per feature, globally. But `feature_ic_scores` is keyed
   `(feature_name, symbol, tf, regime, lookahead, ...)` and `ensemble_weights` is keyed
   `(symbol, tf, regime, weight_version, feature_name)` (migration 168) — a single feature can have
   dozens to hundreds of distinct weight rows across symbols/TFs/regimes. None of the three plans
   state the aggregation rule that collapses per-cell IC pass/fail results into one feature-level
   `active`/`shadow_only` registry status, or which cell(s) a scalar `pre_shadow_weight` column is
   supposed to represent.
2. **`pre_shadow_weight` persistence/restoration target — CONFIRMED gap.** No plan specifies where the
   "restored weight" is actually written back to. `ensemble_weights` is written exclusively by
   `ensemble_trainer.py` on its own schedule — the hook restoring a single `pre_shadow_weight` scalar
   on `feature_registry` does not, by itself, cause `ensemble_weights` rows to change. As written, a
   promotion could flip `feature_registry.status` back to `active` while every `ensemble_weights` row
   for that feature still reflects whatever `ensemble_trainer` last computed (likely a de-facto-zero
   or absent weight, since the feature was excluded from training while `shadow_only`) — the
   "restoration" would be a no-op in the table that ensemble consumers actually read.

Both are genuine, load-bearing gaps, not stylistic nitpicks — a plan that ships as-is risks either
(a) an undefined per-cell-to-feature aggregation rule being invented ad hoc by the executor, or
(b) a promotion that updates registry status without the corresponding weight ever being restored in
the table `ensemble_trainer`/`ensemble_weights` consumers actually read. Idempotency (HIGH) and cache
coherency (HIGH) are plausible but not independently verified against code in this pass — worth
treating as open until Wave 2/3 re-planning addresses them.

---

## Consensus Summary

Only one reviewer ran this pass, so there is no cross-model consensus to report — but the
orchestrating session independently verified (not just deferred to) the two highest-severity
findings against the live schema, and both hold.

### Agreed Strengths
(Single reviewer — restating Codex's assessment, which the orchestrating session concurs with after
independent schema verification)
- Three-wave sequencing (label validation → registry amendments → ic_engine hook) is correctly ordered.
- No new daemon / no parallel state machine — the phase correctly amends the existing `feature_registry`
  machine rather than building a second one.
- Sync/async split (Plan 02's `record_transition_sync`) correctly avoids the event-loop mismatch
  research identified.
- Regime-shift guard evaluated first, before any per-feature transitions — correctly prevents
  dislocation from being misread as mass decay.

### Agreed Concerns (highest priority — action before execution)
1. **[HIGH, CONFIRMED] Feature-level vs. cell-level transition semantics are undefined.** The plans
   never state the rule that aggregates per-(symbol, tf, regime) IC pass/fail results into a single
   feature-level registry status change. This is the single most important gap to close before
   `/gsd:execute-phase 143` — Plan 03's core demotion/promotion logic cannot be implemented correctly
   without it.
2. **[HIGH, CONFIRMED] `pre_shadow_weight` restoration has no defined write path into `ensemble_weights`.**
   Restoring a scalar on `feature_registry` does not by itself change anything `ensemble_trainer`
   reads. Needs an explicit mechanism (e.g., have the hook write/mark a row `ensemble_trainer` will
   pick up next run, or clarify that "restoration" means something narrower than a live weight change).
3. **[HIGH, plausible, not yet independently verified] Idempotency on hook rerun** — no rule preventing
   duplicate `integrity_monitor` rows or re-attempted transitions if the hook (or the whole `ic_engine`
   run) is retried after a partial failure.
4. **[HIGH, plausible, not yet independently verified] Cache coherency** — unclear whether
   `FeatureRegistryService`'s in-memory cache is refreshed between a status/counter write and a
   subsequent `is_promotion_eligible` read within the same hook invocation.

### Divergent Views
N/A — single reviewer this pass.

### Recommendation

Findings 1 and 2 are confirmed, load-bearing, and affect the phase's core correctness — not
edge-case polish. Recommend running `/gsd:plan-phase 143 --reviews` to have the planner resolve the
feature-vs-cell aggregation rule and the weight-restoration write path explicitly before execution,
rather than executing against the current plans and discovering the ambiguity mid-implementation.
