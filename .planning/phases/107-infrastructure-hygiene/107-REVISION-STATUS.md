# Phase 107 Plan Revision Status

**Date:** 2026-05-25
**Trigger:** Cross-AI review feedback (Gemini + Codex)
**Status:** PLANNING COMPLETE — Ready for execution

## Revision Summary

Phase 107 plans have been revised to address all HIGH and MEDIUM priority concerns from cross-AI review. The key changes are:

### 1. Wave 0 Added (Service Inventory + Regression Test) — NEW

**File:** `107-00-PLAN.md`

**Purpose:** Prove full coverage of all 42+ services before any migration begins.

**Deliverables:**
- `tests/integration/test_pipeline_flow.py` — Automated smoke test for hot path
- `scripts/audit-phase107-services.py` — Service inventory script
- `107-00-SERVICE-INVENTORY.md` — Complete coverage matrix
- `107-00-BASELINE.md` — Baseline measurements

**Acceptance:**
- Smoke test passes (Redpanda → DB flow intact)
- All 42+ services inventoried with current state per criterion
- Non-compliant services explicitly listed

**Dependency:** Wave 1 now `depends_on: ["107-00"]`

### 2. Wave 1 Enhanced (Service Consistency) — REVISED

**File:** `107-01-PLAN.md` (revised)

**Key Changes:**
- All tasks now reference Wave 0 inventory for coverage proof
- Added regression smoke test run after code changes (Task 6)
- Added service-by-service acceptance checklist in checkpoint:
  * Clean startup (systemd Active: active (running))
  * Clean SIGTERM shutdown (drain queue, flush buffers, no timeout)
  * No orphan asyncio tasks (grep "task was destroyed")
  * Stall detection fires (stop consumer, verify metric stalls)
  * DB pool closes (log search for "Closing database connection")
  * Metrics visible (curl http://localhost:9100/metrics | grep agent_id)
- Added explicit rollback triggers:
  * Connection errors > 5/min → rollback
  * Orphan tasks detected → rollback
  * Missing metrics → rollback
  * Service fails to start/shutdown → rollback

**Acceptance:**
- All non-compliant services from inventory migrated
- Regression smoke test passes after changes
- Each migrated service passes 6-point acceptance checklist
- No rollback triggers fired during stabilization

### 3. Wave 2 Enhanced (Silent Failure Elimination) — REVISED

**File:** `107-02-PLAN.md` (revised)

**Key Changes:**
- Added writer inventory matrix (Task 1 enhancement)
- Explicit llm_writer_service AttributeError fixes with line numbers
- Dashboard compatibility check after metric type changes
- Regression smoke test run after code changes
- Service-by-service acceptance evidence for writers

**Writer Inventory Matrix Columns:**
- Service name
- Flush trigger (batch size, timeout, interval)
- Shutdown flush behavior (yes/no)
- Span present (yes/no after implementation)
- Failure span attributes (what's logged on error)
- Test coverage (unit test yes/no)

**Acceptance:**
- All writer services have flush span coverage
- AttributeError bugs fixed with reproduction tests
- Grafana dashboards render correctly after metric type changes
- Regression smoke test passes

### 4. Wave 3 Split into Substeps (Complexity Reduction) — RESTRUCTURED

**Files:**
- `107-03-PLAN.md` — Overview (revised)
- `107-03-1-PLAN.md` — Wave 3.1: DAG/systemd consistency (NEW)
- `107-03-2-PLAN.md` — Wave 3.2: Shadow governance SQL (NEW)
- `107-03-3-PLAN.md` — Wave 3.3: Dead code deletion (NEW)
- `107-03-4-PLAN.md` — Wave 3.4: Documentation update (NEW)

**Rationale:** Prevent scope creep by separating operational changes (DAG, SQL) from cleanup (dead code, docs). Each substep has deploy → verify → stabilize gate.

**Wave 3.1 (DAG/systemd):**
- Add 11 missing services to _DAG_ORDER
- Fix systemd unit dependencies
- Resolve cyclic dependencies
- Verify startup/shutdown order

**Wave 3.2 (Shadow SQL):**
- Fix promotion queries: `AND is_shadow = FALSE`
- Skip swarm agents in signal_ledger queries
- Document NULL handling decision
- SQL tests for production/shadow/null cases

**Wave 3.3 (Dead Code):**
- Delete ShadowRecorder, GuardrailsValidator
- Remove 8 dead Settings fields
- Fix TEMPLATE agent bug
- Grep proof of no live references

**Wave 3.4 (Documentation):**
- Update architectural-weakness-assessment.md
- Mark all 9 HYGIENE criteria COMPLETE
- Add Phase 107 Resolutions section
- ONLY after verification passes

## Cross-AI Review Feedback — Response Matrix

| Feedback Item | Priority | Response | Plan |
|--------------|----------|----------|------|
| Service inventory gap | HIGH | Wave 0 added with audit script | 107-00 |
| Verification specificity gap | HIGH | Acceptance checklists, rollback triggers, failure-mode tests | All waves |
| Wave 3 scope creep | HIGH | Split into 4 gated substeps | 107-03-1/2/3/4 |
| Missing regression smoke tests | MEDIUM | test_pipeline_flow.py in Wave 0 | 107-00 |
| Service-by-service acceptance evidence | MEDIUM | 6-point checklist per service | 107-01 |
| Writer inventory matrix | ENHANCEMENT | Added to Wave 2 | 107-02 |
| Explicit llm_writer fixes | ENHANCEMENT | Line numbers, reproduction test | 107-02 |
| Dashboard compatibility | ENHANCEMENT | Grafana smoke test | 107-02 |
| is_shadow NULL handling | ENHANCEMENT | Documented decision | 107-03-2 |

## Plan Files Status

- [x] 107-00-PLAN.md — NEW (Wave 0: Inventory + Baseline)
- [x] 107-01-PLAN.md — REVISED (Wave 1: Service Consistency)
- [x] 107-02-PLAN.md — REVISED (Wave 2: Silent Failure Elimination)
- [x] 107-03-PLAN.md — REVISED (Wave 3 Overview)
- [x] 107-03-1-PLAN.md — CREATED (Wave 3.1: DAG/systemd)
- [x] 107-03-2-PLAN.md — CREATED (Wave 3.2: Shadow SQL)
- [x] 107-03-3-PLAN.md — CREATED (Wave 3.3: Dead Code)
- [x] 107-03-4-PLAN.md — CREATED (Wave 3.4: Documentation)

**All plans complete. Ready for execution.**

## Next Steps for User

1. **Review revision summary** — Confirm all HIGH/MEDIUM feedback addressed
2. **Complete Wave 3 substeps** — Create 107-03-1 through 107-03-4 following enhanced pattern
3. **Execute Wave 0 first** — `/gsd:execute-phase 107 --wave=0`
4. **Then execute serial waves** — Wave 1 → Wave 2 → Wave 3 (auto-gated substeps)

## Success Criteria

Plans pass gsd-plan-checker validation on 6 dimensions:
- [x] Goal alignment — Every task maps to HYGIENE criterion
- [x] Dependencies — Tasks in correct order (inventory → migrate → verify)
- [x] Completeness — All 9 criteria covered with evidence
- [x] Clarity — Rollback criteria explicit, acceptance criteria binary
- [x] Feasibility — 1-2 hour stabilization windows realistic
- [x] Testability — Each task has verification query or test

---

**Planner:** Claude (GSD planner mode)
**Reviewers:** Gemini, Codex (cross-AI review)
**Incorporation:** All HIGH + MEDIUM priority feedback addressed
**Status:** Ready for execution (pending Wave 3 substep completion)
