---
phase: 142B
slug: frame-simulation-counterfactual-tracking-planned
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-09
revised: 2026-07-09
revised_reason: cross-AI review (142B-REVIEWS.md) — H1/H2/H3/H4 + MEDIUM fixes; Per-Task map updated in place, task IDs unchanged
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
| 142B-01-01 | 01 | 1 | FRAME-03 | T-142B-01/09/V5 | Migration DDL asserts corrected CHECK (`closed_ic_decay` in, `closed_reversal` out); composite PK `(frame_id, bar_ts)` contains the partition col so create_hypertable applies (H1); NO FK to alpha_events (M1); APR keys seeded under correct names; alpha_frames added to truncate script; parameterized SQL | unit (schema assertion) + apply-time hypertable check | `pytest tests/unit/test_alpha_frames_schema.py -x` | ❌ W0 (created in-task) | ⬜ pending |
| 142B-01-02 | 01 | 1 | FRAME-01 | T-142B-03/V5 | Pure direction-correct ATR-only geometry with caller-supplied price-unit ATR (NOT read from feature_vectors — H2); idempotent content_key text frame_id; per-(symbol,tf) chunked anti-join (no long txn — L1); parameterized SQL | unit (pure fn + tdd) | `pytest tests/unit/test_alpha_frame_writer_geometry.py tests/unit/test_alpha_frame_writer.py -x` | ❌ W0 (created in-task) | ⬜ pending |
| 142B-01-03 | 01 | 1 | FRAME-01 | — | SHADOW-REVIEW.md frozen with FIVE numeric criteria (M6), day-clustered block-bootstrap method + caveat (H4), gross gate (D-01) + net_expected_r reporting column (D-02) + documented expected-R units (M5) | doc assertion | `test -f docs/plans/SHADOW-REVIEW.md && grep net_expected_r ...` | N/A (doc) | ⬜ pending |
| 142B-02-01 | 02 | 2 | FRAME-02/03/04 | T-142B-09/10 | DIRECTION-AWARE exit (short stop above / target below, pnl sign flip — H3) with executable gap-through fills (L2) + empty-bars-stays-open guard (L3b); day-clustered block-bootstrap gate passes iff clustered ci_lower>0, analytic-CLT above bootstrap_max_n, respects min_strategy_n (H4); MANDATORY short-frame test cases | unit (pure fn + tdd) | `pytest tests/unit/test_counterfactual_tracker_exit_priority.py tests/unit/test_frame_gate.py -x` | ❌ W0 (created in-task) | ⬜ pending |
| 142B-02-02 | 02 | 2 | FRAME-02/03 | T-142B-04/06/08 (OOM/DAG) | One named-server-side-cursor sweep per (symbol,tf) computing ATR+entry+geometry+scan (H2/M2/M4), bar-count scoped (L3c); worker returns serializable rows only, no DB write; per-symbol incremental flush; UPDATE keys (frame_id, bar_ts) + status='open' (M3) | unit (grep guard + mock flush) | `pytest tests/unit/test_counterfactual_tracker.py -x` | ❌ W0 (created in-task) | ⬜ pending |
| 142B-02-03 | 02 | 2 | FRAME-04 | T-142B-05/09/V5 | Gate evaluates on GROSS pnl_r (D-01), in-sample only, per (tf, regime), passes calendar-date cluster_ids into the day-clustered gate (H4), min_strategy_n floor | unit (pure fn) | `pytest tests/unit/test_counterfactual_tracker.py -x` | ❌ W0 (created in-task) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Test scaffolding is created inline as the first (RED) step of each code-producing task rather than in
a standalone Wave 0 plan — ROADMAP.md fixes this phase at 2 plans. Each `tdd="true"` task writes its
failing test before implementation; each schema/doc task writes its assertion test alongside the
artifact. Files created (unchanged by the review revision — the H3/H4 fixes add CASES to existing
files, not new files):

- [ ] `tests/unit/test_alpha_frames_schema.py` — FRAME-03 migration DDL incl. composite-PK / no-FK / hypertable-apply assertions (Plan 01, Task 1)
- [ ] `tests/unit/test_alpha_frame_writer_geometry.py` — FRAME-01 geometry math, long + short (Plan 01, Task 2)
- [ ] `tests/unit/test_alpha_frame_writer.py` — FRAME-01 write/idempotency + expected-R snapshot (Plan 01, Task 2)
- [ ] `tests/unit/test_counterfactual_tracker_exit_priority.py` — FRAME-02/03 DIRECTION-AWARE exit logic incl. mandatory short-stop/short-target/gap-through/empty-bars cases + compute_frame_pnl_r long+short (Plan 02, Task 1)
- [ ] `tests/unit/test_frame_gate.py` — FRAME-04 day-clustered block-bootstrap gate incl. wider-CI-when-clustered + analytic-CLT-path cases (Plan 02, Task 1)
- [ ] `tests/unit/test_counterfactual_tracker.py` — FRAME-02 worker contract + incremental flush + UPDATE-key + gate grouping (Plan 02, Tasks 2-3)
- [ ] No new pytest fixtures anticipated beyond this codebase's convention (in-memory dataclass configs, no live DB in unit tests)

---

## Manual-Only Verifications

*None at the unit tier — all phase behaviors have automated verification. Two execution-time checks are
NOT unit-tested and are exercised via ops runs (see Plan 02 `<post_execution>`): (a) migration 214's
create_hypertable apply-time success is confirmed by applying the migration and querying
`timescaledb_information.hypertables` (review H1 — a text-grep unit test cannot catch a PK/hypertable
incompatibility); (b) FRAME-04's gate against the real 12,258,206-row backlog runs via `--backfill` +
`--evaluate-gate`, while its pass/fail math (including day-clustering) is unit-tested via
`frame_gate_passes`.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (created inline per task)
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter
- [x] Review-revision (H1-H4 + MEDIUM) reflected in the Per-Task map without changing task IDs or file count

**Approval:** approved (planner, 2026-07-09); revised post-review (planner, 2026-07-09)
</content>
