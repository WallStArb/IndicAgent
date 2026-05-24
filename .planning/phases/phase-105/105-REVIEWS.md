---
phase: 105
reviewers: [gemini, codex]
reviewed_at: 2026-05-24T00:00:00Z
plans_reviewed:
  - 105-01-PLAN.md
  - 105-02-PLAN.md
  - 105-03-PLAN.md
  - 105-04-PLAN.md
  - 105-05-PLAN.md
---

# Cross-AI Plan Review — Phase 105

## Gemini Review

### Summary

The Phase 105 plans provide a methodical, risk-aware approach to resolving critical reliability issues, data loss, and architectural drifts. The wave-based execution strategy is well-structured, particularly for handling OTel metric migration and shadow governance, which require multi-service coordination. The plans generally align with the project's high-frequency, event-driven architecture, focusing on fail-fast mechanisms and correct instrumentation.

### Strengths

- **Wave-based execution:** Correctly separates low-risk plumbing (Wave 1) from state-dependent logic changes (Wave 2) and verification (Wave 3).
- **Fail-fast integration:** The shift to `raise` in `FeatureWriterAgent` is a significant improvement over silent failures, aligning with robust systemd lifecycle management.
- **Dependency awareness:** Explicitly acknowledges the dependency of shadow governance on the OTel gauge refactor.
- **Commit management:** Proper handling of Kafka consumer configuration (`enable_auto_commit=False`) in `SwarmLedgerWriterAgent` ensures transaction consistency.

### Concerns

- **MEDIUM — Ghost-run / fail-fast side effects:** While `raise` is correct, `systemd` restart backoff might be too aggressive if database recovery is slow. Consider if `FeatureWriterAgent` needs a circuit breaker pattern or specific `RestartSec` in systemd.
- **LOW — Clock drift / latency instrumentation:** Reusing variables for latency in 105-03 is performant, but ensure `pipeline_latency` captures the correct end-to-end timestamp delta (start of I1 ingress to end of I8 output).
- **LOW — Dead topic removals:** 105-01 suggests removing dead subscriptions. Ensure these topics are not being used for debugging/tracing or by auxiliary agents not listed in the plan.
- **MEDIUM — Shadow auditor promotion logic:** Ensure SG-3 correctly handles the transition for existing plugins. If a plugin's history contains mixed `is_shadow` states, ensure the promotion query doesn't accidentally bias the selection.

### Suggestions

- For 105-02, consider adding a simple stateful retry (e.g., `backoff` library) to the `FeatureWriterAgent` database reconnection before crashing, to reduce systemd flapping.
- During 105-03, include a small validation script or unit test to verify that existing Prometheus dashboards don't break after switching from `UpDownCounter` to `Gauge`.
- For 105-04, double-check the promotion query: ensure `is_shadow = FALSE` doesn't inadvertently filter out legitimate shadow-phase observations that should count toward promotion.
- Once completed, update `docs/architecture/` to reflect these changes in FeatureWriter and ShadowGovernance.

### Risk Assessment

**LOW-MEDIUM.** The changes are surgical and well-scoped. The primary risk is service instability (flapping) if fail-fast mechanisms are too aggressive without proper systemd tuning, and potential minor observability gaps during the migration of OTel metrics. These are adequately mitigated by the planned regression tests in 105-05.

---

## Codex Review

### Summary

The phase is well-scoped around real architectural failure modes, but the plans need tightening before implementation. The biggest issues are offset semantics, shadow promotion SQL, and missing regression coverage for some modified services. Most fixes are directionally correct, but a few plan details could either fail to solve the data-loss class or accidentally disable shadow promotion.

### 105-01: CtxWriter + LLMWriter

**Strengths**
- Correctly targets OTel `.inc()` misuse.
- Fixes a real LLMWriterAgent bug: `self._pool` is not initialized.
- Adds stall watchdog activity for LLM consumption.
- Recognizes that `latest` is unsafe for a persistence writer.

**Concerns**
- **HIGH:** LLM writer currently constructs `KafkaConsumerClient` without `enable_auto_commit=False`. Changing `auto_offset_reset` to `earliest` does not fix pre-write offset commits.
- **MEDIUM:** `auto_offset_reset="earliest"` only affects partitions with no committed offset. Existing consumer groups will not replay skipped data unless offsets are reset or a new group is used.
- **MEDIUM:** Removing `llm.outcomes` and `intelligence.i8` subscriptions because there are "no publishers" may be scope creep. The code still has handlers and persistence tables for those paths.
- **LOW:** `await super()._teardown()` in CtxWriterAgent does not flush the ctx custom buffers because that agent overrides `_do_flush()` and uses `_event_buffer` / `_snapshot_buffer`, not BaseWriterAgent's `_buffer`.

**Suggestions**
- Add `enable_auto_commit=False` to LLM writer and verify manual commit only happens after DB writes.
- Keep dead-topic removal separate unless there is a stronger architecture decision.
- Add `test_llm_writer_service.py` coverage for `execute_command`, `.add()`, liveness, and manual commit config.

**Risk Assessment: MEDIUM-HIGH** — plan misses LLM auto-commit, which is central to the data-loss goal.

### 105-02: FeatureWriter + BarWriter + SwarmLedger

**Strengths**
- Feature writer fail-fast is the right tradeoff; silent DB-disabled operation is worse than restart/backoff.
- Bar writer liveness fix matches BaseAgent watchdog expectations.
- Swarm ledger identifies a real pre-write auto-commit risk.

**Concerns**
- **HIGH:** SwarmLedger is a `BaseAgent`, not `BaseWriterAgent`. If `enable_auto_commit=False` is set, the plan must add explicit `await self._consumer.commit()` after successful `_handle_event()`. Otherwise it will replay messages forever on restart.
- **MEDIUM:** Feature writer fail-fast should ensure `_connect_database()` raises after logging and does not leave `db_manager=None` to continue into Kafka setup.
- **MEDIUM:** Invalid swarm messages and exhausted retry misses need an explicit commit policy.
- **LOW:** Bar writer liveness placement after contract-update routing means contract updates won't count as activity — may be intentional but should be explicit.

**Suggestions**
- For swarm ledger, define offset policy by outcome: success commit, terminal invalid/miss commit, transient exception no commit.
- Add tests for feature writer DB init failure and swarm manual commit behavior.

**Risk Assessment: MEDIUM-HIGH** — disabling auto-commit without an explicit manual commit plan.

### 105-03: OTel Metric Type Fixes

**Strengths**
- Correctly distinguishes counters, point gauges, and histograms.
- Preserving metric names helps Grafana continuity.
- Reusing existing latency variables avoids hot-path overhead.

**Concerns**
- **MEDIUM:** Changing metric instruments requires every call site to use the right method: gauges `.set()`, histograms `.record()`, counters `.add()`.
- **MEDIUM:** Tests that mock latency metrics may expect `.add()` and need updating.
- **LOW:** The local `gauge()` helper still means "up_down_counter"; using `point_gauge()` or direct `create_gauge()` consistently will avoid future confusion.

**Suggestions**
- Add metric API regression tests for representative instruments.
- Search all `SHADOW_*`, `_i1_latency_ms`, `_i7_latency_ms`, and `_pipeline_latency` call sites after implementation.

**Risk Assessment: MEDIUM** — metric type changes are straightforward but easy to miss at call sites.

### 105-04: Shadow Suppression

**Strengths**
- Stamping `is_shadow` in the executor is the right source of truth.
- Filtering shadows from winner selection while preserving ranked observations matches the governance goal.
- Marking shadow rows as `regime_suppressed` prevents lifecycle activation while preserving training/audit evidence.

**Concerns**
- **HIGH:** The plan says to add `AND is_shadow = FALSE` to promotion queries. That is wrong for shadow promotion. Promotion must evaluate shadow rows (which have `is_shadow = TRUE`). Adding `FALSE` would make `n=0` and block promotion forever.
- **MEDIUM:** Winner selection should handle the all-shadow case explicitly and produce no live winner without failing downstream.
- **MEDIUM:** If a shadow signal only gets `status="regime_suppressed"` but keeps `regime_eligible=True`, some metrics may still count it incorrectly.
- **LOW:** `resolution_method` from live-only selection will be stamped onto shadow rows too; tests should lock that behavior down.

**Suggestions**
- Promotion query should filter `AND is_shadow = TRUE` (counting shadow-mode observations); demotion query for live plugins should use `AND is_shadow = FALSE`.
- Add tests for all-shadow bars, mixed shadow/live bars, and auditor promotion sample counts.

**Risk Assessment: HIGH** — until the promotion SQL filter direction is confirmed/corrected.

### 105-05: Regression Tests

**Strengths**
- Covers the highest-risk shadow winner path.
- Includes writer liveness and commit-config tests.
- Full unit suite plus format/lint is appropriate for a hotfix sprint.

**Concerns**
- **HIGH:** Missing LLM writer regression tests despite 105-01 changing LLM writer behavior.
- **MEDIUM:** Missing feature writer fail-fast test.
- **MEDIUM:** Missing metric API tests for 105-03 instrument type changes.
- **MEDIUM:** Swarm ledger tests should assert manual commit after success if auto-commit is disabled.

**Suggestions**
- Add `test_llm_writer_service.py` cases for no `_pool`, `.add()`, liveness, offset config, and topic behavior.
- Add `test_feature_writer_agent.py` case asserting DB connection failure raises.
- Add observability tests asserting shadow gauges expose `.set()` and latencies use `.record()`.

**Risk Assessment: MEDIUM** — proposed tests are useful but incomplete for the modified surface.

### Overall Risk Assessment (Codex)

**MEDIUM-HIGH.** The sprint addresses the right bugs and is mostly cohesive, but three details need correction before coding: (1) LLM writer manual offset control missing, (2) swarm ledger manual commits after disabling auto-commit undefined, (3) shadow auditor promotion SQL filter direction may be inverted.

---

## Consensus Summary

### Agreed Strengths

- Wave-based parallelization correctly isolates non-overlapping file changes (Wave 1) from inter-plan dependencies (Waves 2-3).
- Fail-fast approach in FeatureWriterAgent is the right tradeoff over silent ghost-run data loss.
- Shadow stamp + winner filter + auditor SQL pattern is architecturally sound.
- OTel metric type distinctions (gauge vs counter vs histogram) are correctly identified.
- Preserving metric name strings avoids Grafana dashboard breakage.

### Agreed Concerns

1. **Shadow auditor promotion SQL direction (HIGH — raised by both reviewers):** Both reviewers flag ambiguity/incorrectness around `AND is_shadow = FALSE` in the promotion query. Codex specifically argues this blocks promotion entirely (shadow plugins that qualify have `is_shadow = TRUE` in signal_ledger). Needs resolution before 105-04 executes.

2. **Swarm ledger manual commit missing (HIGH — Codex):** Setting `enable_auto_commit=False` without adding explicit `consumer.commit()` after the DB write creates an infinite replay loop. Even if Gemini didn't name it explicitly, both call out the commit-ordering concern broadly.

3. **LLM writer auto-commit gap (HIGH — Codex):** 105-01 adds `auto_offset_reset="earliest"` but doesn't add `enable_auto_commit=False` to the LLM writer. Parallels the swarm ledger fix but was omitted.

4. **Missing regression coverage (MEDIUM — both):** 105-05 omits tests for LLM writer behavior, feature writer fail-fast, and OTel metric type correctness. These are the three most mechanically subtle fixes.

### Divergent Views

- **Dead topic removal (105-01):** Codex sees it as potential scope creep (handlers and tables still exist for those paths); Gemini accepts it with a caution about auxiliary consumers. Recommend keeping the TODO comment and removal as planned but adding a note in SUMMARY.md that re-wiring is v2.8 scope.
- **CtxWriter super()._teardown() effectiveness:** Codex raises that BaseWriterAgent._teardown() may not drain `_event_buffer` / `_snapshot_buffer` (ctx-specific buffers). Worth reading `base_writer.py` carefully during Task 1 execution as the plan already instructs — the existing guard handles the case.
- **Systemd flapping concern:** Gemini suggests retry logic before crashing; Codex accepts fail-fast. Project CLAUDE.md explicitly defers retry to BaseAgent._setup_with_retry (Phase 106 scope) — fail-fast is correct for Phase 105.

### Priority Actions Before Execution

1. **Clarify promotion SQL in 105-04 Task 3:** Confirm whether shadow plugin promotion counts `is_shadow = TRUE` rows (live-mode filter on demotion only) or both sides. The research doc says "promotion: n >= 100 AND bootstrap_ci_lower(pnl_r) > 0" — verify which `is_shadow` value shadow-mode plugins accumulate in signal_ledger.
2. **Add explicit `consumer.commit()` to swarm ledger plan (105-02 Task 3):** Define commit-by-outcome policy before coding.
3. **Add `enable_auto_commit=False` to LLM writer (105-01 Task 2):** Mirror the swarm ledger fix.
4. **Expand 105-05 test coverage:** Add LLM writer, feature writer fail-fast, and OTel instrument type tests.
