---
phase: 112
reviewers: [gemini, codex]
reviewed_at: 2026-06-02T00:00:00Z
plans_reviewed: [112-01-PLAN.md, 112-02-PLAN.md, 112-03-PLAN.md, 112-04-PLAN.md, 112-05-PLAN.md]
---

# Cross-AI Plan Review — Phase 112: Intelligence Pipeline Signal Integrity

## Gemini Review

## Review of Phase 112: Intelligence Pipeline Signal Integrity

### 1. Summary
The plan is highly structured, logically sequenced, and shows a deep understanding of the systemic nature of the technical debt being addressed. By dividing the work into forensic boundaries (Wave 1), critical logic fixes (Wave 2), lifecycle integrity (Wave 3), architectural cleanup (Wave 4), and performance optimization (Wave 5), you have created a robust roadmap for implementing the `feature_schema_version = 2` mandate. The reliance on atomic migrations and explicit regression testing for "wave isolation" significantly mitigates the risk of downtime or inconsistent data states.

### 2. Strengths
- **Forensic Boundary (Wave 1):** Implementing the schema version at the *insert* path in both writers immediately solves the contamination risk, satisfying the primary goal of Phase 112 before moving into logic changes.
- **Atomicity (Wave 2):** Combining the removal of `SETUP_PRIORITY` and the bump of `SIGNAL_SCHEMA_VERSION` at the *end* of Wave 2 is a sound strategy to maintain consistency.
- **Verification (Wave 4):** Including `test_wave_isolation.py` and `test_no_legacy_features_access.py` forces a clean break from legacy patterns (`frames["features"]`) and provides objective proof of architectural integrity.
- **Defect Coverage:** The plan explicitly calls out the resolution of all 22 identified defects, including tricky edge cases like regime cache cold-starts and backfill labeling.

### 3. Concerns
- **[HIGH] Migration Complexity:** The plan mentions 4 migrations (110-113). If the `signal_ledger_full` view is modified in Wave 1 and schema columns are added in various steps, ensure that the view does not break downstream processes that might expect existing column order or names during the rollout.
- **[MEDIUM] Plugin Migration:** Migrating 73 plugins in Wave 4 (Task 1B) is a massive manual task. The risk of human error in converting `frames["features"]` to typed tier access is high.
- **[MEDIUM] Performance Hit:** The introduction of `flat_features` precomputation and weighted-fair queues (Wave 5) changes the timing profile of the pipeline. Ensure the performance impact of these new overheads is measured against the latency goals.
- **[LOW] Stateful Plugin Risk:** You noted that stateful plugins run despite deadline misses (D-12). If a stateful plugin takes significantly longer than its budget, it could still cascade and cause subsequent pipeline timeouts, even if the outer timeout DLQs the current bar.

### 4. Suggestions
- **Automated Plugin Migration (Wave 4):** Given the 73 plugins, write a small temporary script or regex-based tool to identify all instances of `frames["features"]` and verify the replacement patterns. Do not rely on manual inspection for 73 files.
- **Migration Testing:** Add a "Pre-flight" check in the CI/CD pipeline that validates the migration sequence (110-113) against a schema snapshot of the production TimescaleDB to ensure no breaking changes occur before deployment.
- **Rollback Strategy:** For the atomic commit in Phase 0, define a clear "break-glass" procedure. If the `feature_schema_version` column causes issues with legacy consumers, ensure there is a documented path to quickly revert the writer logic (even if the DB migration stays).
- **Monitoring:** Since you are implementing an output queue drain ratio, ensure you add high-cardinality alerts for the ratio delta between `_high_queue` and `_low_queue` to catch starvation early.

### 5. Risk Assessment
**Overall Risk: MEDIUM**

While the technical plan is excellent, the sheer volume of changes (modifying 73+ plugins, structural DB changes, and pipeline logic) creates a significant surface area for "unknown unknowns." The primary risk is not the design, but the potential for minor implementation discrepancies across 73 plugins. The mandatory regression testing (Wave 4) and atomic staging of the schema version (Wave 1) provide strong guardrails, but the complexity of the manual refactoring in Wave 4 warrants caution. If Wave 4 testing fails, the entire pipeline integrity goal is jeopardized.

---

## Codex Review

## Summary

The five-wave plan is directionally strong and mostly aligned with the phase goals: it establishes a clean-data boundary first, then fixes calibration/ranking/lifecycle defects, then removes architectural coupling and applies ML gates. The main weaknesses are execution risk and a few hidden dependency violations: Wave 1 may miss the real signal writer conversion path, Wave 2's empirical quality-floor query risks violating the "pipeline daemons do not touch DB" rule, Wave 4 is an unusually large 73-file migration, and Wave 5's timeout/deadline design has cancellation and circular-import hazards. I would treat the phase as feasible but high-risk unless each wave gets stricter preflight checks, rollback steps, and targeted tests.

## Wave 1: Forensic Boundary

**Strengths**
- Correctly keeps old rows `NULL` and uses `feature_schema_version = 2` as a forward-only clean marker.
- Explicitly recognizes that adding the Pydantic field is insufficient without hardcoded INSERT wiring.
- Correctly adapts `setup_performance` reset to the live schema by using `sample_size = 0`.
- Defers `SIGNAL_SCHEMA_VERSION` to Wave 2, matching D-03.

**Concerns**
- **[HIGH]** "Atomic commit" is not guaranteed by four separate migration files plus code changes. A partial deploy could expose the column but still write `NULL`, invalidating the boundary.
- **[HIGH]** The plan must include `services/signal_writer.py` conversion from Kafka payload to `LedgerEntry`; repository INSERT wiring alone is not enough if `LedgerEntry` never receives `feature_schema_version`.
- **[MEDIUM]** `DROP VIEW ... CASCADE` for `signal_ledger_full` can silently drop dependent views/grants unless dependencies are audited and restored.
- **[MEDIUM]** Columns are nullable by design, but there is no runtime/assertion guard that new rows are non-null after deploy.
- **[LOW]** Direct historical/backfill INSERT paths should be explicitly classified as out-of-scope or updated.

**Suggestions**
- Add a preflight inventory of all `INSERT INTO signal_ledger` and `INSERT INTO intelligence_features` paths.
- Add a post-deploy canary query: new rows after deploy timestamp must have `feature_schema_version = 2`.
- Wrap Phase 0 deployment in a documented rollback plan and require all four migrations plus code deploy/restart as one release gate.
- Recreate `signal_ledger_full` without `CASCADE` if possible, or list and restore dependent objects.

**Risk Assessment: HIGH**

The design is correct, but a single missed writer path or partial deployment makes the forensic boundary unreliable.

## Wave 2: Critical Logic Fixes

**Strengths**
- Correctly moves calibration from per-signal outputs to filtered CIS, matching the training distribution.
- Adds a publishable confidence floor and rejection metric.
- Uses `RuntimeError` for PERF-03 enforcement, not `assert`.
- Removes `SETUP_PRIORITY` and `long_bias` together, which is the right atomic pairing.
- Keeps `SIGNAL_SCHEMA_VERSION = "v2"` as text and bumps it last.

**Concerns**
- **[HIGH]** The quality-floor "startup query" may violate the rule that pipeline/analyzer daemons do not touch the DB directly. It should be sourced through an allowed bootstrap/cache path, not embedded in pipeline logic.
- **[HIGH]** Existing `apply_calibration` appears list/signal-oriented; CIS-level scalar calibration likely needs a shared scalar helper to avoid awkward reuse or dependency leakage.
- **[MEDIUM]** `CISScorer.score()` may not currently have `symbol`, `tf`, or calibration curves available; the plan should specify the interface change precisely.
- **[MEDIUM]** Auditing and marking 31 incremental plugins in one task risks false compliance. The test only proves the flag exists unless behavior tests verify state write-back.
- **[MEDIUM]** Bumping `SIGNAL_SCHEMA_VERSION` last is good, but "last edit" is not equivalent to an atomic release boundary.
- **[LOW]** Existing tests importing `SETUP_PRIORITY` will need intentional rewrites, not just source removal.

**Suggestions**
- Move empirical floor computation to a permitted service/materializer or load it from an existing cache snapshot.
- Extract calibration interpolation into a scalar helper used by both old tests and new CIS scoring.
- Add behavioral PERF-03 tests for representative incremental plugins, not only a flag audit.
- Add a release checklist: no v2 signal publication until Wave 2 tests pass and Wave 1 boundary canary is green.

**Risk Assessment: HIGH**

This wave changes signal semantics and schema versioning. The plan is conceptually sound, but DB-access placement and calibration interface details need tightening.

## Wave 3: Signal Lifecycle Fixes

**Strengths**
- Properly moves mutable lifecycle fields to `SignalState`.
- Backfill TTL handling matches D-09: dedup only, no false EXIT.
- Addresses restart loss of MAE/MFE and regime cache cold-start.
- Correctly changes signal consumers from `latest` to `earliest`.

**Concerns**
- **[HIGH]** Re-consuming from `earliest` can create a large replay on production topics; dedup safety depends on `_signal_ids` bootstrap completeness and memory behavior.
- **[MEDIUM]** Canonical immutability tests must catch nested mutations, not only direct `sig["status"] = ...`.
- **[MEDIUM]** MAE/MFE publish payload shape must exactly match `SignalLedgerRepository.batch_execute("mae_mfe_update")`; the plan says to verify but should make it an acceptance test.
- **[MEDIUM]** Backfill dedup-only depends on stable `signal_id`; missing/generated IDs could still create duplicate replay behavior.
- **[LOW]** Last-writer-wins regime bootstrap is acceptable, but should log count and collision behavior.

**Suggestions**
- Add a bounded replay test for `earliest` startup with preloaded `_signal_ids`.
- Add a unit test that snapshots canonical dict contents before/after `_evaluate_bar`.
- Add a lifecycle writer test proving `MAE_MFE_UPDATE` updates persisted `mae` and `mfe`.
- Track backfill routed count by `{symbol, tf}` if label cardinality is controlled.

**Risk Assessment: MEDIUM**

The scope is narrow and well-targeted, but replay behavior and exact MAE/MFE persistence need stronger tests.

## Wave 4: Architecture Cleanup

**Strengths**
- Correctly treats `frames["features"]` dual-write removal as structural, with a regression test.
- Recognizes the live grep set is larger than the research undercount.
- Weighted high/low output queues directly address journal starvation.
- Circuit breaker enablement and worker queue gauges improve operational safety.

**Concerns**
- **[HIGH]** Migrating 73 plugin/shared-util files in one wave is very high blast radius; typed-tier mapping mistakes can silently change indicators and signals.
- **[HIGH]** `test_wave_isolation.py` may be brittle for stateful, time-dependent, or floating-point plugins unless fixtures and state are tightly controlled.
- **[MEDIUM]** Creating gauges with the same names in both `per_key_worker_manager.py` and `intelligence_pipeline.py` could duplicate OTel instruments.
- **[MEDIUM]** Two-queue refactor must preserve `task_done`, cancellation requeue, and shutdown semantics for both queues.
- **[MEDIUM]** Circuit breakers enabled globally could alter production behavior immediately; thresholds need telemetry validation.
- **[LOW]** The no-legacy test should avoid failing on its own string literals or docs/comments unless that is intentional.

**Suggestions**
- Split 4-1B internally by tier and run per-tier golden output comparisons.
- Generate a field-to-tier mapping table before edits and include it in the summary.
- Define gauges once and import them, rather than registering duplicate instruments.
- Add output queue tests for high-only, low-only, mixed 5:1, timeout, cancellation, and `join()`.
- Keep circuit breaker rollout observable with counters for opened/skipped plugins.

**Risk Assessment: HIGH**

This is the riskiest wave by code volume and semantic coupling. It needs staged verification, not just grep success.

## Wave 5: Latency + Data Remediation

**Strengths**
- Fixes the `model_dump_json()` nested JSON bug correctly with `model_dump(mode="json")`.
- Adds clean-data gates to key ML/calibration/stat queries.
- Keeps `fast_path` infrastructure-only and avoids marking plugins prematurely.
- Batches output enqueues and precomputes flat features, both valid hot-path improvements.

**Concerns**
- **[HIGH]** `asyncio.wait_for(..., 0.5)` does not cancel threadpool work reliably; plugin state may still mutate after timeout unless state commit boundaries are explicit.
- **[HIGH]** Importing `_build_features_from_event` or `_I1_ALIAS_MAP` from `signal_processor` into `feature_pipeline_executor` may create a circular dependency. Flattening should move to a neutral module.
- **[HIGH]** Training gates appear incomplete. Other readers such as `feature_builder`, `ml_discovery_analyzer`, or weight/training utilities may still consume contaminated rows unless explicitly ruled out.
- **[MEDIUM]** Tier deadline "carry forward on miss" is underspecified: by the time a tier deadline is missed, some plugins may already have run, so per-plugin timeout semantics need clarity.
- **[MEDIUM]** Serialization change may break consumers/tests expecting `{"event": "<json string>"}` unless all consumers are migrated together.
- **[LOW]** `enqueue_many` still enqueues per item internally unless implemented with careful timeout semantics; batching may reduce call overhead but not guarantee atomic output publication.

**Suggestions**
- Move feature flattening and alias handling to a neutral helper module, e.g. `feature_flattening.py`.
- Add timeout tests proving no stale plugin state is committed after a bar DLQ.
- Inventory all `intelligence_features` and `signal_ledger_full` training/calibration readers; gate or explicitly defer each one.
- Add consumer contract tests for the new intelligence event payload shape.
- Define tier budgets in config with documented defaults and metrics for deadline misses.

**Risk Assessment: HIGH**

The latency goals are valid, but cancellation, state consistency, and incomplete ML gates are serious risks.

## Overall Risk

**Overall risk: HIGH.**

The plans cover most of the 22 defects and the sequencing is broadly correct: boundary first, logic second, lifecycle third, architecture fourth, latency/data gates last. However, the phase touches schema, signal semantics, plugin execution, output queues, and ML training inputs in one release sequence. The biggest blockers to "clean-data guarantee" are missed write paths, partial Phase 0 deployment, incomplete downstream query gates, and Wave 4's broad plugin migration. The plans should proceed only with strict wave gates, production canary queries, and explicit inventories for writer paths, training readers, plugin field mappings, and consumers affected by serialization changes.

---

## Consensus Summary

### Agreed Strengths
- **Wave sequencing is correct** (both reviewers): boundary first (Wave 1) before any logic changes is the right approach and prevents contamination from bleeding into post-fix data.
- **Atomicity design** (both): deferring `SIGNAL_SCHEMA_VERSION` bump to end of Wave 2 (D-03) and shipping it after `SETUP_PRIORITY` removal + `long_bias=False` is sound.
- **Regression testing** (both): `test_wave_isolation.py` and `test_no_legacy_features_access.py` are the right structural tests for Wave 4's dual-write elimination.
- **PERF-03 enforcement pattern** (both): `RuntimeError` in `PluginExecutor.__init__` (not `assert`) is the right mechanism.
- **Calibration architecture (Design B)** (both): CIS-level calibration matches the training distribution; per-signal isotonic application was a category error.

### Agreed Concerns

**HIGH priority:**
1. **Missed writer paths (Wave 1)** — Both reviewers flag the risk of incomplete writer coverage. Codex specifically names `signal_writer.py` as a likely missed path. Wave 1's effectiveness depends on ALL write paths including the Kafka payload → LedgerEntry conversion, not just the repository INSERT SQL.
2. **73-plugin migration blast radius (Wave 4)** — Both reviewers identify this as the highest-risk task by code volume. Typed-tier mapping errors can silently corrupt indicator values. Automation (script/codegen) plus per-tier golden output comparison is the consensus mitigation.
3. **asyncio.wait_for cancellation gap (Wave 5)** — Codex flags that `wait_for(timeout=0.5)` does not reliably cancel threadpool/executor work; plugin state may mutate after the bar is DLQed. The state commit boundary needs to be explicit before this is safe.
4. **Circular import risk (Wave 5)** — Importing `_I1_ALIAS_MAP` / `_build_features_from_event` from `signal_processor` into `feature_pipeline_executor` introduces a circular dependency. Both reviewers implicitly and explicitly flag this; the fix is a neutral `feature_flattening.py` module.
5. **Quality-floor DB access (Wave 2)** — Codex flags that the empirical floor "startup query" may violate the DAG invariant that pipeline daemons do not touch the DB directly. The floor should be loaded from an allowed bootstrap/cache path.

**MEDIUM priority:**
6. **`DROP VIEW ... CASCADE` risk (Wave 1)** — Codex: can silently drop dependent views or grants. Need an audit of VIEW dependencies before applying migration 112.
7. **OTel gauge duplication (Wave 4)** — Both reviewers note that defining the same gauge name in two files (`per_key_worker_manager.py` and `intelligence_pipeline.py`) creates duplicate OTel instruments. Define once, import from the defining module.
8. **PERF-03 behavioral tests missing (Wave 2)** — Codex: the test only proves `_state_migration_complete = True` flag is set; it does not verify actual state write-back behavior. A flag-only test can pass on plugins that fake compliance.
9. **Serialization consumer migration (Wave 5)** — Any consumer expecting `{"event": "<json string>"}` will break when the publish changes to `model_dump(mode="json")`. Consumer contract tests should be added before the Wave 5 deploy.
10. **Incomplete ML training gates (Wave 5)** — Codex: `feature_builder`, `ml_discovery_analyzer`, and weight utilities may still query contaminated rows. The gate inventory in the plan may be incomplete.

### Divergent Views
- **Overall phase risk:** Gemini rates the phase **MEDIUM** overall (design is excellent, execution surface area is the main concern); Codex rates it **HIGH** (multiple hidden dependency violations, cancellation gaps, and incomplete ML gates are structural risks, not just execution risks). The divergence reflects that Gemini focuses on the plan's structural soundness while Codex probes for runtime hazards. Codex's higher rating reflects real execution risks worth addressing before Wave 5.
- **Wave 1 sufficiency:** Gemini treats Task 4 (writer INSERT wiring) as sufficient for the boundary; Codex identifies that the Kafka-payload-to-LedgerEntry conversion may be a missed upstream step. Both agree the INSERT path is necessary; only Codex flags the potential upstream gap.
- **Quality floor placement:** Both flag it as a risk, but Codex is more prescriptive about where it should live (permitted bootstrap path, not inline pipeline logic). Gemini's concern is limited to testing the migration sequence.
