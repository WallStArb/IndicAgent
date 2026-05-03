---
phase: 078-i8-alpha-feedback-loop
plan: "03"
subsystem: alpha-swarm
tags: [graduation, shadow-registry, spearman, skeptic-v1, migration]
dependency_graph:
  requires: [078-01]
  provides: [skeptic_v1_shadow_enrollment, graduation_loop_spearman]
  affects: [shadow_registry, signal_lineage, alpha_swarm_agent]
tech_stack:
  added: [scipy.stats.spearmanr]
  patterns: [TDD, async-graduation-loop, idempotent-enrollment, threshold-gate]
key_files:
  created:
    - production/migrations/078_alpha_swarm_shadow_enrollment.sql
    - tests/integration/test_swarm_graduation_loop.py
  modified:
    - services/alpha_swarm_agent.py
    - tests/unit/service_tests/test_alpha_swarm_agent.py
decisions:
  - "Use source='skeptic_v1' column (not agent_name) — signal_lineage schema uses 'source' per 073 migration"
  - "Store rho in last_eval_ev_r column — shadow_registry schema (077) has no last_metric JSONB column; use existing last_eval_ev_r FLOAT"
  - "Reset _demotion_streak to 0 immediately after demotion fires — prevents re-demotion on next cycle when state is already shadow"
  - "_run_graduation_cycle() extracted from _graduation_loop() as testable unit — avoids asyncio.sleep in unit tests"
  - "_GRAD_MIN_N=100 hard gate before Spearman (T-78-09) — no statistical computation under threshold"
metrics:
  duration: "14 minutes"
  completed_date: "2026-04-30"
  tasks_completed: 2
  files_changed: 4
---

# Phase 78 Plan 03: AlphaSwarm graduation loop (skeptic_v1 shadow → live via Spearman) Summary

Wires the skeptic_v1 swarm agent into the shadow_registry state machine with Spearman-based promotion and demotion gates. skeptic_v1 must earn the right to live status through statistical proof (N≥100, ρ>0, p<0.05) — never by default.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Migration 078 — idempotent skeptic_v1 enrollment | f3340942 | production/migrations/078_alpha_swarm_shadow_enrollment.sql |
| 2 (TDD RED) | Failing graduation tests | 2f495269 | tests/unit/service_tests/test_alpha_swarm_agent.py |
| 2 (TDD GREEN) | _graduation_loop implementation | be79a082 | services/alpha_swarm_agent.py, tests/unit/service_tests/test_alpha_swarm_agent.py, tests/integration/test_swarm_graduation_loop.py |

## Acceptance Criteria Verification

- `grep -q "FROM signal_lineage" services/alpha_swarm_agent.py` — PASS
- `grep -q "spearmanr" services/alpha_swarm_agent.py` — PASS
- `! grep -q "signal_transform_log" services/alpha_swarm_agent.py` — PASS
- All 17 unit tests pass (13 pre-existing + 4 new graduation tests)
- `.venv/bin/ruff check services/alpha_swarm_agent.py` — PASS (0 errors)
- Migration applied idempotently: first run INSERT 0 1, re-run INSERT 0 0
- skeptic_v1 enrolled in shadow_registry: `SELECT * WHERE component_name='skeptic_v1'` returns 1 row

## Deviations from Plan

**1. [Rule 1 - Bug] schema column mismatch: last_metric JSONB does not exist**
- **Found during:** Task 2 (implementing UPDATE)
- **Issue:** Plan specified `last_metric = $3::jsonb` but migration 077 defines `last_eval_ev_r FLOAT`, `last_eval_n INTEGER` etc. — no JSONB column.
- **Fix:** Updated UPDATE to use `last_eval_ev_r = $3` (float rho) + `last_eval_n = $2` matching actual schema
- **Files modified:** services/alpha_swarm_agent.py
- **Commit:** be79a082

**2. [Rule 1 - Bug] signal_lineage uses 'source' column, not 'agent_name'**
- **Found during:** Task 2 (writing the SELECT query)
- **Issue:** Plan spec showed `AND l.agent_name = 'skeptic_v1'` but the actual 073_signal_lineage.sql schema has column `source TEXT NOT NULL` (not agent_name)
- **Fix:** Query uses `AND l.source = 'skeptic_v1'` matching actual schema
- **Files modified:** services/alpha_swarm_agent.py
- **Commit:** be79a082

**3. [Rule 2 - Missing functionality] prediction field extraction for JSONB dicts**
- **Found during:** Task 2 analysis of LineageRecorder.record() output
- **Issue:** The recorder stores `multiplier` in the record but wraps `payload` in metadata. The `_run_graduation_cycle` query returns `prediction` column (JSONB) not `multiplier` directly — needs extraction logic.
- **Fix:** Added dict extraction: `pred_raw.get("score") or pred_raw.get("multiplier")` with float coercion + isfinite guard (T-78-08)
- **Files modified:** services/alpha_swarm_agent.py
- **Commit:** be79a082

## TDD Gate Compliance

- RED commit: `2f495269` — 4 failing tests (AttributeError: _run_graduation_cycle)
- GREEN commit: `be79a082` — all 17 tests pass
- No REFACTOR needed — code clean on first pass

## Stubs

None — all data paths are wired. The graduation loop queries live DB tables; integration test verifies end-to-end promotion.

## Threat Surface Scan

No new network endpoints or auth paths introduced. All DB operations are scoped UPDATE/INSERT targeting existing tables with WHERE component_type='swarm_agent' (T-78-10). No new trust boundaries.

## Self-Check: PASSED

| Item | Status |
|------|--------|
| production/migrations/078_alpha_swarm_shadow_enrollment.sql | FOUND |
| services/alpha_swarm_agent.py | FOUND |
| tests/integration/test_swarm_graduation_loop.py | FOUND |
| Commit f3340942 (migration) | FOUND |
| Commit 2f495269 (RED tests) | FOUND |
| Commit be79a082 (GREEN implementation) | FOUND |
