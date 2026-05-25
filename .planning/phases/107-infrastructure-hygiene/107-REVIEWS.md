---
phase: 107
reviewers: [gemini, codex]
reviewed_at: 2026-05-25T11:02:00Z
plans_reviewed: [107-01-PLAN.md, 107-02-PLAN.md, 107-03-PLAN.md]
---

# Cross-AI Plan Review — Phase 107

## Gemini Review

### Summary
Phase 107 is a well-structured, high-maturity remediation effort targeting systemic technical debt that threatens the stability of the upcoming AI platform work. By adopting a serialized wave execution strategy—prioritizing service consistency, followed by failure elimination, and concluding with complexity reduction—the plan mitigates the risk of catastrophic "rollback hell" associated with fundamental infrastructure changes (e.g., `BaseAgent` lifecycle, DB pool management). The explicit reliance on binary SQL verification and Grafana stabilization gates aligns perfectly with the project's Renaissance-inspired engineering standards.

### Strengths
- **Serialized Wave Execution (D-01):** The commitment to 1-2 hour stabilization gates between waves is the most critical design strength, allowing for isolation of side effects in high-risk tasks.
- **Binary Verification:** The use of binary SQL success queries as a gated requirement ensures that "success" is objectively measurable rather than qualitatively assumed.
- **Renaissance Alignment:** The focus on silent failure elimination (flush spans, shadow governance) before complexity reduction demonstrates a clear understanding of system-level observability requirements.
- **Granularity:** Individual tasks are well-scoped and mapped to specific technical debt (e.g., `AttributeError` fixes, metric type corrections), making them highly verifiable.

### Concerns
- **Dependency Risks (MEDIUM):** While Wave 1 standardizes `BaseAgent` and `DatabaseManager`, there is a latent risk that migrating complex services like `signal_replay_auditor_agent` could expose hidden timing or concurrency bugs not caught by unit tests.
- **Missing Regression Target (LOW):** The plan does not explicitly list a "smoke test" suite to run *before* and *after* each wave to ensure core ingestion and persistence flows remain unbroken (e.g., checking data continuity in TimescaleDB).
- **Dead Code Deletion Scope (LOW):** Task 3.6 involves significant deletions. While low-risk via `git`, the sheer number of removals (`ShadowRecorder`, `GuardrailsValidator`, 8 settings fields) could theoretically break internal references if they are more deeply integrated than currently mapped.

### Suggestions
- **Add "Baseline Continuity" Checks:** For every Checkpoint, execute a brief diagnostic query to compare total event counts in Redpanda vs. ingested rows in TimescaleDB to ensure no silent data loss is occurring during the `BaseAgent` transitions.
- **Automated Smoke Test:** Supplement the SQL verification with an automated smoke test (e.g., `tests/integration/test_pipeline_flow.py`) that executes before *and* after each wave to verify the hot path.
- **Dead Code "Staging" (for deletion):** Before full deletion in Wave 3, consider moving dead code components to a `deprecated/` directory for 48 hours to ensure no runtime errors are triggered by late-running crons or infrequently triggered service paths.
- **Agent ID Consistency (Refinement):** Ensure Task 1.4 specifically updates the `BaseAgent` constructor to *enforce* `agent_id` presence via type hinting or a runtime check, rather than relying on manual implementation.

### Risk Assessment
**Overall Risk: MEDIUM**

*Justification:* The plan is technically sound and the risks are well-contained by the serialized execution strategy. The "Medium" rating reflects the inherent complexity of migrating core infrastructure (`BaseAgent` and DB pools) in a live, streaming environment. The risk is minimized by the planned stabilization intervals and the revertible nature of the proposed changes. Provided the binary SQL verification queries are comprehensive, the path to success is highly probable.

---

## Codex Review

### Summary
The Phase 107 plans are directionally strong and well aligned with the stated goal: remove infrastructure debt that could create silent failures before the AI platform phase. The serial wave strategy is appropriate given the dependency chain and operational risk: lifecycle and DB pool standardization can affect process shutdown, connection behavior, metrics identity, and writer reliability, so stabilizing before changing persistence semantics is prudent. The main weakness is verification specificity. The plans name SQL and Grafana checkpoints, but several tasks need sharper acceptance criteria, rollback boundaries, and service-by-service evidence so the "binary TRUE" outcome is not treated as a substitute for proving each changed behavior works under failure conditions.

### Plan 107-01 — Wave 1: Service Consistency

#### Strengths
- Correctly starts with lifecycle and DB pool consistency before writer instrumentation and AttributeError fixes.
- Focuses on foundational service behavior: `BaseAgent`, SIGTERM handling, stall detection, DB pool construction, and canonical `agent_id` labels.
- Keeps the scope tight enough for a high-risk first wave.
- Includes a stabilization window before proceeding, which is justified for lifecycle and connection changes.

#### Concerns
- **HIGH:** Only two services are explicitly migrated to `BaseAgent`, while the success criterion says all 42+ services must use `BaseAgent` lifecycle. The plan should clarify whether these are the only remaining non-compliant services or just the first two.
- **HIGH:** DatabaseManager standardization mentions only `swarm_ledger_writer_agent`, but the roadmap says 3 services need pool standardization.
- **MEDIUM:** SIGTERM handling and stall detection are mentioned at the phase level but not as explicit task acceptance checks.
- **MEDIUM:** `agent_id` label consistency in `BaseAgent` may not be sufficient if services emit metrics outside the base class or use custom metric wrappers.
- **MEDIUM:** Verification of `service_auditor` metric queries is read-only unless paired with tests or live metric samples proving label compatibility.
- **LOW:** No explicit rollback criteria are defined for Wave 1 failures.

#### Suggestions
- Add an inventory task: list all 42+ services with current lifecycle pattern, DB pool pattern, and metric label usage.
- Expand Task 3 to include all 3 services requiring `DatabaseManager.create_pool()` and JSONB codec verification.
- Add explicit acceptance checks for each migrated service:
  - clean startup
  - clean SIGTERM shutdown
  - no orphan tasks
  - stall detection still emits expected telemetry
  - DB pool closes on teardown
- Add metric compatibility checks using live scrape data or test fixtures proving `agent_id` appears consistently.
- Define rollback gates: for example, rollback if connection errors, duplicate service registrations, missing metrics, or shutdown hangs exceed a threshold during stabilization.

#### Risk Assessment
**Overall risk: MEDIUM-HIGH.** The scope is small, but lifecycle and pool behavior are foundational. The wave is appropriate, but the plan needs stronger proof that it satisfies the "all services" criteria rather than only fixing named examples.

### Plan 107-02 — Wave 2: Silent Failure Elimination

#### Strengths
- Targets the highest-value failure class: silent writer loss and broken persistence instrumentation.
- Correctly waits until after lifecycle and DB pool standardization.
- Includes both behavioral fixes and observability fixes.
- Addresses known concrete defects: `.inc()` vs `.add()`, teardown errors, ghost-run mode, incorrect OTel instruments.

#### Concerns
- **HIGH:** Flush span coverage is listed for `ctx_writer_agent` and `feature_writer_agent`, but the phase says all writer services need flush span coverage. The plan should confirm whether only these writers are missing coverage.
- **HIGH:** "Fix AttributeError bugs in llm_writer_service" is too broad without naming the failing code paths and expected tests.
- **MEDIUM:** Adding spans is not enough unless span lifecycle covers success, partial flush, retry, failure, timeout, and shutdown-drain paths.
- **MEDIUM:** Metric type migrations can break dashboards or alerts if names, temporality, or aggregation semantics change.
- **MEDIUM:** Gauge replacement for shadow metrics needs clarity on callback/observable gauge vs synchronous gauge depending on the OTel SDK in use.
- **LOW:** Latency histogram bucket boundaries are not mentioned; bad buckets can make the metric technically correct but operationally weak.

#### Suggestions
- Add a writer inventory matrix:
  - service name
  - flush trigger
  - batch size
  - shutdown flush behavior
  - span present
  - failure span attributes
  - test coverage
- Make `llm_writer_service` fixes explicit:
  - exact AttributeError sites
  - reproduction test
  - regression test
- Require spans to include minimum attributes such as `agent_id`, destination table/topic, batch size, success/failure status, duration, and dropped/retried count where available.
- Add dashboard compatibility checks after metric type changes.
- Verify metric semantics in collector/backend, not only in code.
- Add failure-injection tests for writer flush exceptions and shutdown flush behavior.

#### Risk Assessment
**Overall risk: MEDIUM.** The fixes are necessary and well scoped, but instrumentation changes can produce false confidence unless verified through failure paths and actual telemetry ingestion. The plan achieves the phase goal if it broadens "flush span coverage" to every writer, not only the named services.

### Plan 107-03 — Wave 3: Complexity Reduction

#### Strengths
- Appropriately scheduled after higher-risk runtime behavior changes.
- Addresses governance and dead code, both of which reduce risk before AI platform expansion.
- Includes DAG/systemd consistency, which is important for operational correctness.
- Shadow promotion filtering directly protects signal quality and prevents feedback contamination.

#### Concerns
- **HIGH:** Dead code deletion is bundled with DAG changes, SQL governance filters, documentation updates, and systemd dependency verification. This wave may be broader than the prior waves and harder to debug if something fails.
- **HIGH:** Adding 11 missing services to `_DAG_ORDER` can change startup/shutdown behavior. This should be treated as runtime-sensitive, not purely cleanup.
- **HIGH:** Shadow promotion query changes need careful migration/testing to avoid excluding valid production signals due to nullable or missing `is_shadow` values.
- **MEDIUM:** `AND is_shadow = FALSE` may behave differently from `COALESCE(is_shadow, FALSE) = FALSE` if historical rows have nulls.
- **MEDIUM:** "Skip swarm agents" needs a precise definition: by `agent_id` prefix, service type, table, registry membership, or metadata field.
- **MEDIUM:** Updating the architectural weakness assessment before final verification risks documenting completion prematurely.
- **LOW:** "TEMPLATE bug" is under-specified and should be linked to a concrete file and test.

#### Suggestions
- Split Wave 3 internally into gated substeps:
  1. DAG/systemd consistency
  2. shadow governance SQL changes
  3. dead code deletion
  4. documentation update
- Move documentation update to the final task after all verification passes.
- Add SQL tests or fixtures for:
  - production signal included
  - shadow signal excluded
  - null `is_shadow` behavior explicitly decided
  - swarm ledger rows excluded
- Define `_DAG_ORDER` acceptance criteria:
  - all deployed units present
  - startup order matches declared dependencies
  - shutdown order safe for writers and DB consumers
  - priorities justified in comments or docs
- For dead code deletion, require `rg` proof of no live references plus test/import checks.

#### Risk Assessment
**Overall risk: MEDIUM-HIGH.** It is framed as complexity reduction, but DAG and SQL promotion changes affect runtime behavior and data correctness. The wave is valid, but it needs finer-grained gates to avoid mixing operational dependency changes with cleanup.

### Serial Wave Strategy
The serial strategy is appropriate, not overly conservative. Phase 107 touches lifecycle management, database pools, telemetry semantics, writer flush behavior, promotion queries, and service dependency ordering. Those are cross-cutting systems where parallel waves would make causality hard to establish during incidents.

The stabilization windows are especially justified after Wave 1 and Wave 2. Wave 1 can create process and connection regressions. Wave 2 can create silent or noisy telemetry regressions. Wave 3 can change startup order and signal eligibility. Serial execution is slower, but it materially improves rollback clarity.

The main improvement is to make each stabilization gate evidence-based: specific SQL results, service health, logs, metric samples, traces, and dashboard checks.

### Cross-Plan Gaps
- **HIGH:** The plans do not explicitly show how the final binary SQL verification query maps to all 9 criteria.
- **HIGH:** "All 42+ services" appears in success criteria, but the task lists only name a subset.
- **MEDIUM:** Rollback plans are not defined per wave.
- **MEDIUM:** Runtime verification is mentioned, but failure-mode verification is thin.
- **MEDIUM:** No explicit owner or artifact is named for evidence collection.
- **LOW:** Security impact is minimal, but DB query changes should still avoid broadening access or bypassing tenant/source filters if any exist.

### Recommended Additions
- Add a Phase 107 verification matrix with one row per criterion:
  - criterion
  - files/services touched
  - static check
  - runtime check
  - SQL query
  - dashboard/panel
  - rollback trigger
- Require before/after metric samples for label and instrument changes.
- Require trace samples for each writer flush span.
- Require deployment inventory proving all services are covered, not just the known problematic ones.
- Add null-handling decisions for shadow governance SQL.
- Treat `_DAG_ORDER` changes as operational behavior changes with their own stabilization check.

### Final Risk Assessment
**Overall Phase 107 risk: MEDIUM-HIGH.**

The phase is necessary and the ordering is sound. The greatest risk is not scope creep; it is false closure: marking criteria complete because named fixes landed, while some services, writer paths, metrics, or historical data edge cases remain uncovered. With a service inventory, criterion-by-criterion verification matrix, explicit rollback gates, and failure-path tests, the plans should be strong enough to execute.

---

## Consensus Summary

### Agreed Strengths
Both reviewers agree on these key strengths:

1. **Serial wave execution is appropriate and well-justified** — Both Gemini and Codex validate that the 1-2 hour stabilization gates between waves are critical for isolating side effects in high-risk infrastructure changes. The strategy prevents "rollback hell" and improves causality debugging.

2. **Binary SQL verification is a strong design choice** — Both reviewers appreciate the use of binary success queries as gated requirements. This ensures success is objectively measurable rather than qualitatively assumed.

3. **Renaissance engineering principles are well-aligned** — The focus on silent failure elimination (flush spans, AttributeError fixes) before complexity reduction demonstrates clear understanding of system-level observability requirements.

4. **Wave ordering is sound** — Both agree that starting with service consistency (BaseAgent lifecycle, DB pools), then moving to failure elimination (writer flush spans, metrics), and finishing with complexity reduction (DAG completeness, dead code deletion) is the correct dependency sequence.

### Agreed Concerns
Both reviewers raised these concerns — **high priority to address**:

1. **Service inventory gap (HIGH — Codex, implied in Gemini's "subset" concern):** Plans name specific services (e.g., `signal_replay_auditor`, `ctx_writer`) but success criteria say "all 42+ services" or "all writer services." The plan should clarify whether these are the only remaining non-compliant services or just the first batch. **Fix:** Add an inventory task listing all 42+ services with current lifecycle/DB pool/metric label patterns to prove full coverage.

2. **Verification specificity gap (HIGH — Codex, MEDIUM — Gemini):** Plans name SQL and Grafana checkpoints but lack sharp acceptance criteria, rollback boundaries, and failure-mode testing. Binary TRUE/FALSE is not enough; need proof that behavior works under failure conditions. **Fix:** Add explicit rollback triggers per wave, failure-injection tests for writer flush exceptions, and evidence-based stabilization checks (service health, logs, metric samples, traces).

3. **Wave 3 scope creep risk (HIGH — Codex, LOW — Gemini):** Wave 3 bundles DAG changes, SQL governance filters, dead code deletion, documentation updates, and systemd verification. This mixes operational dependency changes with cleanup, making debugging harder if something fails. **Fix:** Split Wave 3 into internally gated substeps: (1) DAG/systemd, (2) shadow governance SQL, (3) dead code deletion, (4) documentation update after verification passes.

4. **Missing regression smoke tests (MEDIUM — both):** No automated smoke test suite to run before/after each wave to ensure core ingestion and persistence flows remain unbroken. **Fix:** Add `tests/integration/test_pipeline_flow.py` that executes before and after each wave to verify hot path, plus baseline continuity checks (Redpanda event counts vs. TimescaleDB ingested rows).

5. **Missing service-by-service acceptance evidence (MEDIUM — Codex):** Tasks lack explicit acceptance checks for SIGTERM handling, stall detection, DB pool closure, clean shutdown. **Fix:** Add explicit acceptance checks for each migrated service: clean startup, clean SIGTERM shutdown, no orphan tasks, stall detection emits telemetry, DB pool closes on teardown.

### Divergent Views

- **Gemini emphasizes dependency risk** (timing/concurrency bugs in `BaseAgent` migration) while **Codex emphasizes verification gap** (lack of failure-mode testing and rollback criteria). Both are valid — the plan should address both concerns.

- **Gemini views dead code deletion as low-risk** (git revert is trivial) while **Codex views it as higher-risk** (bundled with other changes in Wave 3). Codex's concern is valid — the risk is not deletion itself but the bundling scope.

### Recommended Actions (Priority Order)

**Must fix before execution (BLOCKERS):**
1. Add service inventory proving "all 42+ services" coverage (Plan 01)
2. Clarify that only named writers are missing flush span coverage OR add inventory proving full coverage (Plan 02)
3. Add explicit rollback criteria per wave with trigger thresholds (all plans)
4. Split Wave 3 into internally gated substeps (Plan 03)

**Should fix before execution (WARNINGS):**
5. Add automated smoke test suite for before/after wave verification
6. Add explicit acceptance checks for SIGTERM/stall detection/DB pool closure (Plan 01)
7. Add failure-injection tests for writer flush exceptions (Plan 02)
8. Add null-handling decisions for `is_shadow` SQL filter (Plan 03)
9. Move documentation update to final task after all verification passes (Plan 03)

**Nice to have (ENHANCEMENTS):**
10. Add baseline continuity checks (Redpanda vs. TimescaleDB row counts)
11. Require before/after metric samples for label/instrument changes
12. Add writer inventory matrix (flush trigger, batch size, shutdown behavior, span attributes)
13. Make `llm_writer_service` AttributeError fixes explicit (exact sites, reproduction test)
14. Add dashboard compatibility checks after metric type changes

---

**To incorporate this feedback into planning:**

```bash
/gsd:plan-phase 107 --reviews
```

This will replan Phase 107 taking into account the structured feedback from both Gemini and Codex.
