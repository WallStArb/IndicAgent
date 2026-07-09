---
phase: 142B
slug: frame-simulation-counterfactual-tracking-planned
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-09
---

# Phase 142B — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (project-standard) |
| **Config file** | none dedicated to this phase — inherits project `pytest.ini`/`pyproject.toml` |
| **Quick run command** | `.venv/bin/pytest tests/unit/test_alpha_frame_writer.py tests/unit/test_counterfactual_tracker.py -x` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -q` |
| **Estimated runtime** | ~60 seconds (full suite) |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/test_alpha_frame_writer.py tests/unit/test_counterfactual_tracker.py -x`
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 142B-01-01 | 01 | 1 | FRAME-03 | T-142B-01/V5 | Migration DDL asserts corrected CHECK constraint (`closed_ic_decay` in, `closed_reversal` out); APR keys seeded under correct names; parameterized SQL | unit (schema assertion) | `pytest tests/unit/test_alpha_frames_schema.py -x` | ❌ W0 (created in-task) | ⬜ pending |
| 142B-01-02 | 01 | 1 | FRAME-01 | T-142B-03/V5 | Frame geometry math (ATR-only path, S/R NULL) uses APR-loaded params; idempotent content_key write; anti-join parameterized SQL | unit (pure fn + tdd) | `pytest tests/unit/test_alpha_frame_writer_geometry.py tests/unit/test_alpha_frame_writer.py -x` | ❌ W0 (created in-task) | ⬜ pending |
| 142B-01-03 | 01 | 1 | FRAME-01 | — | SHADOW-REVIEW.md frozen with gross gate (D-01) + net_expected_r reporting column (D-02) | doc assertion | `test -f docs/plans/SHADOW-REVIEW.md && grep net_expected_r ...` | N/A (doc) | ⬜ pending |
| 142B-02-01 | 02 | 2 | FRAME-02/03/04 | — | Exit-trigger priority (stop > target > max_hold > ic_decay); bootstrap gate passes iff ci_lower>0, respects min_strategy_n | unit (pure fn + tdd) | `pytest tests/unit/test_counterfactual_tracker_exit_priority.py tests/unit/test_frame_gate.py -x` | ❌ W0 (created in-task) | ⬜ pending |
| 142B-02-02 | 02 | 2 | FRAME-02/03 | T-142B-04/06 (OOM/DAG) | Worker returns serializable rows only, no DB write inside worker, named server-side cursor for bar scans (no plain cursor) | unit (grep guard) | `pytest tests/unit/test_counterfactual_tracker.py -x` | ❌ W0 (created in-task) | ⬜ pending |
| 142B-02-03 | 02 | 2 | FRAME-04 | T-142B-05/V5 | Gate evaluates on GROSS pnl_r (D-01), in-sample only, per (tf, regime), min_strategy_n floor | unit (pure fn) | `pytest tests/unit/test_counterfactual_tracker.py -x` | ❌ W0 (created in-task) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Test scaffolding is created inline as the first (RED) step of each code-producing task rather than in
a standalone Wave 0 plan — ROADMAP.md fixes this phase at 2 plans. Each `tdd="true"` task writes its
failing test before implementation; each schema/doc task writes its assertion test alongside the
artifact. Files created:

- [ ] `tests/unit/test_alpha_frames_schema.py` — FRAME-03 migration DDL (Plan 01, Task 1)
- [ ] `tests/unit/test_alpha_frame_writer_geometry.py` — FRAME-01 geometry math (Plan 01, Task 2)
- [ ] `tests/unit/test_alpha_frame_writer.py` — FRAME-01 write/idempotency (Plan 01, Task 2)
- [ ] `tests/unit/test_counterfactual_tracker_exit_priority.py` — FRAME-02/03 exit logic (Plan 02, Task 1)
- [ ] `tests/unit/test_frame_gate.py` — FRAME-04 bootstrap gate (Plan 02, Task 1)
- [ ] `tests/unit/test_counterfactual_tracker.py` — FRAME-02 worker contract + gate grouping (Plan 02, Tasks 2-3)
- [ ] No new pytest fixtures anticipated beyond this codebase's convention (in-memory dataclass configs, no live DB in unit tests)

---

## Manual-Only Verifications

*None — all phase behaviors have automated verification. FRAME-04's gate evaluation against the real 12,258,206-row `alpha_events` backlog is exercised via `--backfill` mode at execution time, not as a manual-only check; its pass/fail math is unit-tested via the bootstrap gate function.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (created inline per task)
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved (planner, 2026-07-09)
