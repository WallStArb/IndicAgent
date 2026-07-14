---
phase: 160
reviewers: [fable]
reviewers_attempted_failed:
  - name: codex
    reason: "Usage limit hit — OpenAI Codex CLI returned 'You've hit your usage limit... try again at Jul 17th, 2026 6:25 PM.' Configured as review.default_reviewers."
  - name: antigravity
    reason: "CLI errored with 'timeout waiting for response' on two attempts (default and 8m --print-timeout), including after --add-dir was supplied. Environment/session issue, not a design objection."
  - name: coderabbit
    reason: "Requires interactive browser OAuth login (automatic_login_failed); cannot complete headlessly in this session."
reviewed_at: "2026-07-14T14:55:00Z"
plans_reviewed:
  - 160-01-PLAN.md
  - 160-02-PLAN.md
  - 160-03-PLAN.md
  - 160-04-PLAN.md
---

# Cross-AI Plan Review — Phase 160

**Note on reviewer composition:** `review.default_reviewers` is configured to `["codex"]`. Codex was
rate-limited (retry available 2026-07-17), Antigravity errored out in this environment, and
CodeRabbit requires interactive browser auth this session couldn't complete. Fable (a genuinely
different Claude model, not the Sonnet session that authored the plans, invoked cold via a fresh
Agent spawn with no memory of the planning conversation) was used as the fallback reviewer. This is
same-vendor rather than cross-vendor, so treat it as a partial substitute for the configured
cross-AI review, not an equivalent one — re-run `/gsd:review 160 --codex` after 2026-07-17 if a true
cross-vendor opinion is still wanted.

## Fable Review

### 1. Summary

These are unusually well-grounded plans: the source doc's SQL and Python are real and internally consistent, the doc-edit anchors exist verbatim in both target files, the todo-numbering claims (109 taken, 112 pending, 118 next free) are correct against the live tree, migrations do top out at 231, and the wiring claims about `ops_ensemble_weight_compare.py` (pool still open at the final `return 0`, `strata`/`stratum_data`/`challenger_by_stratum` in scope, `strata` is the champion-challenger intersection so no KeyError) all check out against the actual script. The reviewer verified the bare float-equality assertions hold exactly (`(0.04+0.02)/2 == 0.03` and `(0.02+0.06)/2 == 0.04` are both True in CPython). The CAS design is sound and fails conservative. However, the review found one design-level problem that can structurally deadlock the promotion mechanism this phase exists to prove (the F3 evidence-mass floor's `eval_n - last_eval_n` approximation), a second selection-bias layer the F8 winner's-curse guard does not cover, a genuine idempotency defect in migration 232, an APR key that is dead-on-arrival for all five seeded concepts, and a backward-compat verification that is currently vacuous because `alpha_ensemble_ic` has zero rows.

### 2. Strengths

- **Pure-core / transactional-apply split** (`decide_comparison_action` vs `record_comparison_outcome`) is the right shape: every invariant is testable without a DB, and the 20-test suite covers the guard ordering, the CAS race, and the F8 baseline rule with exact assertions.
- **CAS fails conservative.** The zero-row CAS path returns `blocked_status_race` with no transition row; a stale double-read of `promotion_consecutive` can only under-count wins (delaying promotion), never double-promote. The transition insert and gate update sit inside the same transaction as the CAS. Parameter counts in `_TRANSITION_INSERT_SQL` (12 columns, `'promotion'` literal + $1-$11) match the execute call.
- **D-01 risk isolation is genuinely good reasoning**: proving CAS apply logic on a near-static, manually-triggered domain before touching the live `ic_engine.py` write path is exactly the right sequencing, and the plans hold that boundary consistently (`feature_registry_service.py` read-only, zero feature rows seeded).
- **The stale-todo-109 correction (D-03) is threaded properly** through 160-04: verified next-free number, consistency grep across both docs and the filename, explicit "never write todo 109."
- **The operational guard against recording the invalidated pre-todo-094 A/B pair** is stated in three places (plan notes, threat register T-160-06, source doc Step 6). Given the endgame is live capital, refusing to seed the registry with a known-invalid outcome is the single most important operational detail here, and the plans get it right.
- **Seed content quality is high**: the `e1_shrunk_ic` "deployed but never formally proven, status stays candidate" annotation and the E4 conflation guard (`weight_half_life_days` is not E4) are exactly the kind of ten-year-queryable honesty the phase goal claims.
- Migration-number re-verification at execution time, `left(content,40)` annotation idempotency guard, and the `to_regclass('concept_gate_template') IS NULL` anti-scope-creep check are all concrete and executable.

### 3. Concerns

#### HIGH

- **H-1: The F3 evidence-mass floor can structurally deadlock promotion, and the phase cannot detect it.** `blocked_evidence_floor` fires when `eval_n - last_eval_n < min_new_observations` (2000). But `eval_n` is the *total* summed `n_independent` over the compared strata, not a count of newly accrued observations. Under rolling corpus windows (backfill depths are fixed per TF: 5m:5y, 1h:15y, etc.), successive corpus builds slide the window rather than grow it, so `eval_n` between builds is approximately constant and the delta is ~0, possibly negative. With `min_promotion_consecutive=2`, promotion requires a *second* eval that passes this floor, so if the delta doesn't grow by 2000 between corpus builds, **no candidate can ever promote through the automated path**, and D-02's entire sequencing gate ("feature migration only after one real promotion/demotion cycle") waits on an event that may be structurally unreachable. The source doc admits this is an approximation (judgment call (c)) but never sanity-checks its viability. Could not verify empirically because `alpha_ensemble_ic` is currently empty (0 rows, corpus rebuild in flight). Per the project's own "measure, don't defer" rule, this needs a bounded empirical check: compare summed `n_independent` across two successive corpus builds' `alpha_ensemble_ic` vintages before trusting the 2000 floor.

#### MEDIUM

- **M-1: `eval_n` is composition-sensitive in both directions, making the F3 floor both spoofable and spuriously blocking.** `strata` is the *intersection* of champion and challenger coverage, so `eval_n` moves when coverage changes, not when evidence accrues: dropping strata gives a negative delta (permanent block), adding strata or switching `alpha.ensemble_ic.gate_lookahead` (APR, currently `'fast'`) inflates the delta with zero new data. Also, HOLD strata (degenerate p-values, no verdict rendered) still contribute their full `n_independent` to `eval_n`, so unevaluable strata count as consumed evidence mass toward passing `min_gate_n`.
- **M-2: The F8 winner's-curse guard misses a second selection layer.** `eval_metric` = mean `ic_ci_lower` over *WIN strata only*. Conditioning on winning inflates the per-round metric before F8's across-rounds mean ever runs, so `baseline_metric` is still systematically selection-biased upward, just at stratum grain instead of round grain. Compounding: a promotion transition row records `gate_n = eval_n` (all 20 strata) next to a metric computed from perhaps 1 winning stratum, so the logged evidence mass does not describe the logged metric's sample. Combined with `won = any-WIN`, two consecutive 1-of-20-strata wins produce `status=active` with a baseline built entirely from the two cherry-picked cells. BH-FDR and the CI-lower citation rule mitigate but do not remove this. At minimum the transition row should also record the WIN-strata count and WIN-strata-only n, so the ten-year-later reader can see how narrow the promotion evidence was.
- **M-3: Migration 232 is not idempotent, contradicting 160-01's own must_have.** `config_history`'s PK is `(timestamp, config_key, version)` and the insert uses `NOW()`, so every re-run inserts 3 new audit rows; `ON CONFLICT DO NOTHING` can never fire because the timestamp differs. The must_have says "Both migrations are idempotent (re-run yields INSERT 0 0)" but only 233 is, and only 233 is ever actually re-run in the acceptance criteria. Fix: guard the history insert with `WHERE NOT EXISTS (SELECT 1 FROM config_history WHERE config_key=... AND version=1)`.
- **M-4: The `ensemble_strategy_min_observations` APR key is dead on arrival.** Migration 233 seeds `min_gate_n=1000` as a *non-NULL per-concept value* on all 5 gate rows, and per-concept values override the APR default. So the APR key exists, is documented as "operator may tune," appears on the `/config/parameters` dashboard, and tuning it silently does nothing for every concept that exists. Either seed `min_gate_n` NULL (inherit, like `min_promotion_consecutive`/`min_new_observations` deliberately do) or drop the key. As written it violates the APR philosophy the migration itself cites.
- **M-5: The backward-compat "byte-identical" acceptance is unverifiable and currently vacuous.** No step captures the pre-change output to diff against, and `alpha_ensemble_ic` has 0 rows right now, so the Step 6 smoke run will hit the "no comparable strata" early-exit, never reaching the modified tail of `main()` or the report table. The smoke will pass while exercising none of the changed code region. Add: capture golden output on main before branching (or fixture-drive the report path), and note that with the table empty, `--challenger-concept` would also silently record nothing (early-exit precedes the registry block, no `REGISTRY:` line).
- **M-6: Losses leave no durable trail, which undercuts the phase's stated goal.** `record_loss` overwrites the single mutable gate-cache row (`last_eval_*`), and the transition log only writes on promotion. `concept_eval_run` was deliberately excluded (F7, locked, not re-litigating the table), but as shipped, "why don't we use e2 anymore" is answerable ten years from now only if a human writes an annotation; the accumulated negative evidence itself evaporates on the next eval. A cheap fix inside existing scope: allow the compare script to append a `source='empirical'` annotation per recorded outcome, or log a non-status-changing transition-log row type. Worth a deliberate decision rather than an accident of the F7 exclusion.

#### LOW

- **L-1:** Same-corpus guard remembers only the *last* `corpus_build_ref`; an A-B-A replay passes. Acceptable given monotone WEIGHT_EPOCHs, but the transition log could be consulted for a complete check.
- **L-2:** `record_win`/`record_loss` gate-cache updates are not CAS'd and the load happens outside any transaction; concurrent evaluators can lose an update. Fails conservative and the domain is a manual ops script, but worth a code comment before the `domain='feature'` follow-on inherits the pattern under `ic_engine` write pressure.
- **L-3:** All `REGISTRY: FAILED` paths return exit 0. Consistent with this script's "informational, exit 0" convention today, but the moment the recording path is invoked from `ops_corpus_pipeline_run.sh` automation, a failed registry write becomes a silent failure, the exact class this project's principles forbid. Flag it in the follow-on todo.
- **L-4:** `--champion-concept` is free text, never validated against the registry, and lands verbatim in immutable transition `notes`. A typo becomes a permanent audit-trail lie.
- **L-5:** `blocked_status_race` returns from *inside* `async with conn.transaction()`, which commits (an empty tx) rather than rolling back. Harmless, but the code comment "the whole transaction... is aborted" is inaccurate and will confuse a future reader.
- **L-6:** CONTEXT.md's code_context claims the `domain` CHECK "already includes `'hmm_variant'`, `'ic_method'`, `'regime_model'`, `'confluence'`," but migration 232's CHECK is only `('feature','ensemble_strategy')`. Future domains need a constraint migration; the CONTEXT statement is wrong about the shipped schema.
- **L-7:** `concept_gate.fdr_required=true` is decorative: nothing in `ConceptRegistryService` reads it. FDR enforcement lives entirely upstream in the compare script, so any future second caller of `record_comparison_outcome` bypasses it with no guard. A one-line comment on the column, or a service-side assertion, would prevent a false sense of enforcement.
- **L-8:** Source doc Task 7's commit message reads "close todo 058" while the action closes 112. Plan 160-04's number-correction discipline covers "109" strings only; the executor copying verbatim will write a misleading commit message.
- **L-9:** Wave 1 runs 160-01 and 160-02 in parallel, but the source doc creates a single feature branch in Task 1 Step 1. Two parallel executors committing to one branch in this project's known shared-dir setup is its documented git-index race. The plans never state the branch mechanics for parallel execution.
- **L-10:** `promotion_eval_metrics` grows unboundedly for an active concept (every `record_win` appends). Cosmetic at this domain's eval cadence.

### 4. Suggestions

1. **Before executing 160-03**, run the bounded empirical check for H-1: once the corpus rebuild produces two `alpha_ensemble_ic` vintages, measure the actual `sum(n_independent)` delta between them. If it's structurally ~0, redefine the F3 delta (e.g., against the corpus build's new-bar count, or against per-stratum `n_independent` growth summed over the *same* strata set) before the floor is load-bearing. This is a one-query check, not a redesign.
2. Change migration 233 to seed `min_gate_n` as NULL (M-4), and add a `WHERE NOT EXISTS` guard to migration 232's `config_history` insert (M-3). Both are two-line diffs to SQL that hasn't shipped yet.
3. In `_registry_outcome` or the transition insert, additionally record `win_strata_count` and WIN-only summed `n_independent` (fits in existing `notes` if schema changes are unwanted) so promotion narrowness is auditable (M-2).
4. Add a golden-output capture step to 160-03's smoke check (run the script on main, save output, diff after change), and explicitly note the empty-table caveat so a vacuous pass isn't recorded as verification (M-5).
5. Make the losses-audit-trail question (M-6) an explicit line in the new follow-on todo 118 if not addressed now, alongside L-3's exit-code hardening, since both bite exactly when this mechanism gets automated.
6. Have 160-04's executor also correct the Task 7 commit message to name 112 (L-8), and have the phase orchestrator serialize wave-1 commits or use worktrees (L-9).

### 5. Risk Assessment

**MEDIUM.** Execution risk is genuinely low: the plans are verbatim-copy plans over already-written, internally consistent code, with correct anchors, correct numbering, verified scope guards, and a sound CAS core; nothing here endangers live pipelines (new tables only, report-only path preserved, invalidated A/B explicitly fenced off). The risk is concentrated in *design viability of the gating math*, not in the build: the F3 evidence-mass approximation (H-1) may make the promotion cycle unreachable, which would silently stall D-02's entire follow-on sequencing, and the stratum-level selection bias in `baseline_metric` (M-2) writes a permanently inflated number into the exact table whose purpose is honest ten-year evidence. Both are cheap to fix before shipping and expensive to fix after rows exist. Fix M-3/M-4 in the migration SQL pre-apply, commit to the H-1 empirical check as a phase exit condition, and this drops to LOW.

---

## Consensus Summary

Only one reviewer completed (Fable); the configured cross-vendor reviewers (Codex, Antigravity,
CodeRabbit) all failed for environmental reasons documented above, not design objections. No
cross-reviewer consensus/divergence synthesis applies with a single respondent — treat every
finding above as a single independent opinion, not a corroborated consensus. The two findings worth
weighing most heavily before execution are H-1 (F3 evidence-mass floor may structurally block
promotion under rolling-window corpus rebuilds) and M-3/M-4 (migration 232's `config_history`
non-idempotency and the dead-on-arrival `min_gate_n` APR key) — both are pre-execution SQL/logic
fixes, cheap now and expensive after rows exist in a live registry.
