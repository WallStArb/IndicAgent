---
phase: 143
reviewers: [codex, fable]
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

## Fable Review (independent)

Reviewed 2026-07-06, against the REVISED 143-02-PLAN.md and 143-03-PLAN.md (post-replan commits
`3e47494a`, `05ba47f9`). Plan 01 treated as fixed context (executed, 143-01-SUMMARY.md). Every claim
below was checked against live schema (`psql`) and current source, not against the plans' own
self-citations. This is the first pass on the revised plans by a reviewer that did not write them.

### Verdict on the four original Codex findings

**Finding 1 (feature-vs-cell aggregation) - RESOLVED, verified.**
Plan 03 now states the rule explicitly (must_haves truth 1-2, objective §1): transition unit is the
FEATURE; demotion fires when the material-fail fraction of the feature's active cells this run is
>= (1 - alpha.ensemble.meta_fdr_min_fraction). The supporting claims hold against code:
`feature_registry.feature_name` is the sole PK (migration 172); `ic_engine.py:1764-1767` builds
`feature_status_map` per-feature from registry status at run start, so all of a feature's cells carry
one status stamp; `ensemble_trainer.py:261-269` (`_meta_eligible`) uses the same constant at the same
feature-level granularity. The plan's own honesty note is also accurate: I verified the trainer's
`fdr_pass_rows` query (`ensemble_trainer.py:425-437`) has NO `training_window_end` filter, so the
plan correctly does NOT overclaim cross-consistency with the trainer's historical eligibility check.
Residual (LOW, noted as N7 below): the two denominators also differ in eligibility filters, and the
plan never pins whether a "cell" is (tf, regime) or (tf, regime, lookahead) - see N3.

**Finding 2 (pre_shadow_weight write path) - RESOLVED, verified, and the right call.**
The revision drops the column instead of inventing a write path. Evidence checks out exactly:
`ensemble_trainer.py:744-748` is the sole `INSERT INTO ensemble_weights` in the codebase, with
`ON CONFLICT ... DO UPDATE SET weight = EXCLUDED.weight`; `_process_stratum` (lines 535-549) rebuilds
weights from this run's `feature_ic_scores` rows filtered `feature_status_at_eval = 'active'`
(line 544); there is no prior-weight read anywhere in the file. So a restored scalar would indeed be
dead, and status-flip + natural recompute is the only mechanism that respects the sole-writer
invariant. The acknowledged one-run lag (hook runs after this run's stamps are written) is real and
correctly characterized. Plan 03's grep-based acceptance criterion (no INSERT/UPDATE ensemble_weights
in ic_engine) locks it.

**Finding 3 (idempotency on hook rerun) - MOSTLY RESOLVED, one residual gap (see N1a).**
Three mechanisms now exist and are individually sound: (a) integrity_monitor UNIQUE on
(monitor_type, training_window_end, metric_name, COALESCE(subject,'')) + ON CONFLICT DO NOTHING;
(b) hook short-circuit keyed on training_window_end (Plan 03 step 0); (c) Plan 02's optimistic
`WHERE status = from_status` lock with rowcount==0 rolling back the log INSERT too (verified feasible:
`write_conn` is autocommit-off via `_batch_utils.py:34`, so `with conn:` gives real transaction
semantics). BUT the ordering leaves a window: transitions and counter advances run at step 4, the
idempotency fact is written at step 5. A crash between them means a rerun re-executes step 4.
Transitions are protected by (c); `advance_shadow_counters_sync` is NOT - it is a plain increment
with no run keying, so a rerun double-increments `consecutive_shadow_passes` and double-adds
`observations_since_demotion`, inflating promotion evidence. Tagged MEDIUM below (N2a).

**Finding 4 (cache coherency) - RESOLVED, verified feasible.**
Plan 02 must_haves truth 5 + Task 2 explicitly require both sync methods to mutate
`self._features[feature_name]` on successful commit, with a dedicated cache-coherency test, and
`is_promotion_eligible` reads counters from the cache. This matches the existing implementation
pattern exactly - the async path already does the same mutation
(`feature_registry_service.py:261-263`), and `_LOAD_QUERY` extension is specified so `load_sync`
caches the counters at run start. Within one hook invocation the sequence
advance-counters -> eligibility-read is coherent by construction. Closed.

### New findings (introduced or exposed by this revision)

- **HIGH (N1): No counter reset on demotion - repeat-decay features get an instant re-promotion.**
  `observations_since_demotion` and `consecutive_shadow_passes` are created with DEFAULT 0
  (migration 202) and only ever mutated by `advance_shadow_counters_sync` (increment/reset-on-fail
  and add). Nothing in either plan zeroes them when a feature is DEMOTED. First decay cycle is fine
  (columns start at 0), but after a promote -> re-demote cycle the counters still hold the values
  that satisfied the floors at the previous promotion (>= 2 passes, >= 2000 obs, never reset).
  One passing run later, `is_promotion_eligible` is trivially True and the feature re-promotes after
  a single run instead of re-earning 2 passes + 2000 observations. This defeats the evidence bar in
  exactly the oscillation scenario lifecycle routing exists to prevent. Fix is one line of semantics:
  `record_transition_sync` (or the hook's demotion step, same transaction) must reset both counters
  to 0 when to_status='shadow_only'. Should be added to Plan 02 Task 2 (and a test) before execution.

- **MEDIUM (N2a): `advance_shadow_counters_sync` is not rerun-safe (residual of finding 3).**
  As described under Finding 3: crash after step 4, before the step-5 fact, and a rerun double-counts
  a run's passes/observations. Cheapest fix: write the per-run gate-evaluation fact and the counter
  advances in one transaction, or key counter advances on training_window_end (e.g. a
  `last_counter_window` column checked in the UPDATE's WHERE, mirroring the optimistic-lock pattern).

- **MEDIUM (N3): "Cell" silently includes 4 lookahead rows; recovery observations are ~4x overcounted.**
  POOLED cross-sectional rows exist per (feature, tf, regime, lookahead_bars) - PK verified, and live
  data confirms 4 distinct lookaheads. Plan 03's cell query neither filters nor groups by lookahead,
  so `new_observations = sum(n_independent)` counts the same underlying bars once per horizon -
  4 overlapping views of one window are not independent observations. The 2000-obs recovery floor is
  effectively ~500. The demotion FRACTION is unharmed (numerator and denominator scale together, and
  the trainer's meta gate is equally lookahead-blind), but the promotion evidence floor is materially
  weakened. Specify the intended semantics (e.g. max or single-lookahead n_independent per (tf,
  regime)) before execution.

- **MEDIUM (N4): Standing-weight lookup keys on the globally most recent weight_version.**
  Plan 03 interface + step 1 use `ew.weight_version = (SELECT weight_version FROM ensemble_weights
  ORDER BY computed_at DESC LIMIT 1)`. Today this is safe (live table holds exactly one version,
  'v1', 103 rows) but `ensemble_trainer` explicitly supports per-run epoch overrides via
  `--weight-version` (ensemble_trainer.py:840), built for the E1/E2 champion/challenger A/B that is
  still pending. The first challenger epoch written after this hook ships would silently become the
  materiality gate's weight source. Read the champion version from APR `alpha.ensemble.weight_version`
  instead (the same key the trainer resolves), or select latest per (tf, regime) at that version.

- **MEDIUM (N5): Zero-cell runs are undefined.** The hook is inserted unconditionally after the
  `if equity_model_enabled and corpus_cs_rows:` block (ic_engine.py:2048-2053). A run with the equity
  model disabled, or a per-symbol-only run, yields zero POOLED cells for this training_window_end:
  the regime-shift fraction is a division by zero and every demotion denominator is 0. Neither the
  plan steps nor the behavior tests cover the empty population. Add an explicit "no cells -> log and
  return (write no fact)" rule so a symbols-only run doesn't poison the idempotency key either.

- **MEDIUM (N6): The staleness alert cannot fire for the failure mode it exists to catch.**
  `ic_engine_last_run_age_days` is only set DURING a run of a oneshot batch process. If ic_engine
  stops running entirely (T-143-08's actual scenario), no new samples are exported and `age >
  staleness_alert_days` never evaluates true - the design detects a too-long gap retroactively, at
  the start of the NEXT run, when it is no longer stale. LIFECYCLE-05's intent needs an
  absence-style alert evaluated by something that is alive (e.g. Prometheus `time() -` last
  `job_completed_total{job="ic-engine..."}` sample, per the D-06 contract ic_engine already emits),
  with the in-run gauge kept as a secondary diagnostic. At minimum document the limitation.

- **LOW (N7): Demotion denominator differs from the trainer's meta-gate denominator.** The trainer
  restricts its per-feature cell population to eligible cells (`ic_ci_lower > 0 AND reliable AND
  ic_sharpe_hac IS NOT NULL`, ensemble_trainer.py:425-437); the hook's denominator is ALL active
  cells. "Same pass/fail semantics" in Plan 03's objective is therefore looser than stated - the
  plan-checker NOTE already concedes divergence on the time axis; this adds a population axis.
  Acceptable as designed (the hook's rule is self-contained and deterministic), but the wording
  should not imply equivalence.

- **LOW (N8): Stale manifest metadata after migration 203.** `ic_engine.py:2122-2123` lists
  `is_decaying` and `decay_detected_at` in the manifest's `columns_written` for feature_ic_scores.
  Migration 203 drops those columns; the list is a plain Python literal so nothing breaks, but the
  manifest will assert columns that no longer exist. One-line cleanup that belongs in Plan 02's
  drop task.

### Verdict

The replan genuinely closed the two confirmed HIGH findings - not cosmetically. The
pre_shadow_weight resolution in particular is the correct first-principles call (delete, don't
plumb), and both plans' evidence citations survived independent verification against live schema and
code with no overclaims found. Findings 3 and 4 are closed in design, with one residual
non-idempotent path (counters). The revision does, however, introduce one new HIGH: the missing
counter reset on demotion, which deterministically breaks the promotion evidence bar on the second
decay cycle of any feature.

**Overall risk: MEDIUM.** Down from HIGH, but not execution-ready as-is. Before
`/gsd:execute-phase 143`: (1) add counter reset on demotion to Plan 02 (N1 - required); (2) pin the
lookahead semantics for `new_observations` (N3) and the zero-cell rule (N5) in Plan 03 - both are
one-paragraph plan edits; (3) switch the standing-weight lookup to the APR champion weight_version
(N4). N2a and N6 can ship as documented limitations if noted in the SUMMARY, though both fixes are
cheap.

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

### Update (2026-07-06, after Fable independent pass on the revised plans)

The replan was subsequently reviewed independently by Fable against the revised 143-02/143-03 plan
text. Status of the four agreed concerns as of that pass:

1. Feature-vs-cell aggregation — **RESOLVED and independently verified** (rule now explicit; all
   supporting code/schema citations check out).
2. pre_shadow_weight write path — **RESOLVED and independently verified** (column dropped;
   status-flip + natural ensemble_trainer recompute; sole-writer invariant preserved).
3. Idempotency — **mostly resolved** (integrity_monitor UNIQUE key + short-circuit + optimistic
   lock all verified sound); residual: `advance_shadow_counters_sync` is not rerun-safe on a crash
   between hook step 4 and step 5 (Fable N2a, MEDIUM).
4. Cache coherency — **RESOLVED** (explicit cache-mutation-on-commit contract + test, consistent
   with the existing async-path pattern).

The Fable pass found one NEW HIGH not present in the original review: lifecycle counters are never
reset on demotion, so a feature's second demotion inherits satisfied floors and re-promotes after a
single passing run (Fable N1). Revised consensus: overall risk **MEDIUM** — do not execute until
N1 (counter reset), N3 (lookahead/observation semantics), and N5 (zero-cell rule) are folded into
the plans; N4 (weight_version pinning) strongly recommended given the pending E1/E2 A/B.

### Update (2026-07-06, findings folded into the plans)

N1, N3, N4, and N5 are now folded directly into `143-02-PLAN.md` / `143-03-PLAN.md`:

- **N1 (counter reset on demotion)** — `record_transition_sync` now zeroes both
  `consecutive_shadow_passes` and `observations_since_demotion` in the same UPDATE whenever
  `to_status == 'shadow_only'` (Plan 02, must_haves + Task 2).
- **N3 (lookahead overcounting)** — the hook's per-run query now pins `lookahead_bars = config.lookahead_mid`
  (`alpha.ic.lookahead.mid`, reused key) before any aggregation, so a "cell" is exactly one row per
  (feature_name, tf, regime) (Plan 03, objective + Task 2).
- **N4 (weight_version pinning)** — the standing-weight JOIN now binds `ew.weight_version` to
  `alpha.ensemble.weight_version` (the same APR key `ensemble_trainer` defaults to), replacing the
  `ORDER BY computed_at DESC LIMIT 1` recency lookup (Plan 03, objective + Task 2).
- **N5 (zero-cell rule)** — the hook now returns immediately with no `integrity_monitor` write when
  the per-run query yields zero POOLED rows for the training_window_end (Plan 03, objective + Task 2).
- **N8 (stale manifest entries)** — folded into Plan 03 Task 2 as a one-line cleanup alongside the
  migration 203 column drops.

**Accepted as documented limitations, no plan change required** (per Fable's own recommendation):
N2a (`advance_shadow_counters_sync` not rerun-safe on a crash between hook steps 4-5 — residual of
finding 3) and N6 (in-run staleness gauge cannot detect ic_engine having stopped entirely — needs a
Prometheus absence alert, out of scope here). Both are now called out explicitly in Plan 03 so
`143-03-SUMMARY.md` documents them rather than silently shipping unremarked.

All four folded fixes are plan-text edits only — `143-02-PLAN.md` and `143-03-PLAN.md` were not
executed yet, so no source code changed. Overall risk assessment for execution readiness: the
plans as they now stand address every N1/N3/N4/N5 gap Fable identified; re-review not required
before `/gsd:execute-phase 143` unless the executor deviates from the specified mechanism.
