---
phase: 142B
slug: frame-simulation-counterfactual-tracking-planned
status: draft
nyquist_compliant: false
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
| 142B-01-XX | 01 | 1 | FRAME-01 | V5 | Frame geometry math (ATR-only path, S/R NULL) uses APR-loaded params, no hardcoded thresholds | unit (pure fn) | `pytest tests/unit/test_alpha_frame_writer_geometry.py -x` | ❌ W0 | ⬜ pending |
| 142B-01-XX | 01 | 1 | FRAME-01 | V5 | `AlphaFrameWriter` idempotent write via `content_key`-derived `frame_id`, parameterized SQL only | unit | `pytest tests/unit/test_alpha_frame_writer.py -x` | ❌ W0 | ⬜ pending |
| 142B-02-XX | 02 | 2 | FRAME-02/03 | — | Exit-trigger priority order (stop > target > max_hold > ic_decay) | unit (pure fn) | `pytest tests/unit/test_counterfactual_tracker_exit_priority.py -x` | ❌ W0 | ⬜ pending |
| 142B-02-XX | 02 | 2 | FRAME-02 | V4/T (OOM) | `CounterfactualTracker` worker returns serializable rows only, no DB write inside worker, named server-side cursor for bar scans | unit | `pytest tests/unit/test_counterfactual_tracker.py -x` | ❌ W0 | ⬜ pending |
| 142B-01-XX | 01 | 1 | FRAME-03 | — | Migration DDL asserts corrected CHECK constraint (`closed_ic_decay` in, `closed_reversal` out) | unit (schema assertion) | `pytest tests/unit/test_alpha_frames_schema.py -x` | ❌ W0 | ⬜ pending |
| 142B-02-XX | 02 | 2 | FRAME-04 | — | Bootstrap gate function passes iff `ci_lower > 0`, respects `min_strategy_n` floor | unit (pure fn) | `pytest tests/unit/test_frame_gate.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_alpha_frame_writer_geometry.py` — stubs for FRAME-01 geometry math
- [ ] `tests/unit/test_alpha_frame_writer.py` — stubs for FRAME-01 write/idempotency
- [ ] `tests/unit/test_counterfactual_tracker_exit_priority.py` — stubs for FRAME-02/03 exit logic
- [ ] `tests/unit/test_counterfactual_tracker.py` — stubs for FRAME-02 worker contract (no DB write in worker)
- [ ] `tests/unit/test_alpha_frames_schema.py` — stubs for FRAME-03 migration DDL
- [ ] `tests/unit/test_frame_gate.py` — stubs for FRAME-04 bootstrap gate
- [ ] No new pytest fixtures anticipated beyond this codebase's convention (in-memory dataclass configs, no live DB in unit tests)

---

## Manual-Only Verifications

*None — all phase behaviors have automated verification. FRAME-04's gate evaluation against the real 12,258,206-row `alpha_events` backlog is exercised via `--backfill` mode at execution time, not as a manual-only check; its pass/fail math is unit-tested via the bootstrap gate function.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
