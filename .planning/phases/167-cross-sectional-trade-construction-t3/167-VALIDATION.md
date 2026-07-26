---
phase: 167
slug: cross-sectional-trade-construction-t3
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-26
---

# Phase 167 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4+ (`pytest-asyncio` 1.1+, `asyncio_mode=auto`) |
| **Config file** | `pytest.ini` (repo root) |
| **Quick run command** | `.venv/bin/pytest tests/unit/test_cross_sectional_spread_tracker.py -x` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -q` |
| **Estimated runtime** | ~30-60s quick, several minutes full suite |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/test_cross_sectional_spread_tracker.py -x`
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green, PLUS a live `--evaluate-gate` run
  producing a real (not mocked) Validation Gate 1 verdict — a pure unit-test pass does not
  itself constitute "the construction is validated" (per RESEARCH.md's Sampling Rate section)
- **Max feedback latency:** ~60s (unit tests are pure-function, no live DB required per
  RESEARCH.md's stated test shape — mirrors `test_counterfactual_tracker.py`'s no-live-DB
  convention for unit-level tests)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 167-01-01 | 01 | 1 | Migration: `construction_spreads` hypertable + APR seeds | T-167-01 | APR values range/type-validated at load (V5) | integration (requires_db) | `pytest tests/integration/ -k construction_spreads_schema -x` | ❌ W0 | ⬜ pending |
| 167-02-01 | 02 | 1 | Decile split (Minimal Design step 2) | — | N/A | unit | `pytest tests/unit/test_cross_sectional_spread_tracker.py::test_decile_split -x` | ❌ W0 | ⬜ pending |
| 167-02-02 | 02 | 1 | Turnover across run boundary (Pitfall 4) | — | N/A | unit | `pytest tests/unit/test_cross_sectional_spread_tracker.py::test_turnover_across_run_boundary -x` | ❌ W0 | ⬜ pending |
| 167-02-03 | 02 | 1 | Cost-hurdle net-of-turnover math (D-05) | T-167-02 | Malformed/out-of-range APR fails loud, never silently clamps | unit | `pytest tests/unit/test_cross_sectional_spread_tracker.py::test_cost_hurdle_sweep -x` | ❌ W0 | ⬜ pending |
| 167-03-01 | 03 | 2 | Incremental watermark scoping (Pitfall 3) | — | N/A | integration (requires_db) | `pytest tests/integration/ -k cross_sectional_spread -x` | ❌ W0 | ⬜ pending |
| 167-04-01 | 04 | 3 | Validation Gate 1 evaluation (`--evaluate-gate`) | — | N/A | unit | `pytest tests/unit/test_cross_sectional_spread_tracker.py::test_evaluate_gate -x` | ❌ W0 (adapt `test_counterfactual_tracker.py`'s gate-evaluation shape) | ⬜ pending |
| 167-05-01 | 05 | 4 | Validation Gate 2 (attribution honesty regression) | — | N/A | unit | `pytest tests/unit/test_cross_sectional_spread_tracker.py::test_attribution_honesty -x` | ❌ W0 (new statistical work, no existing analog — RESEARCH.md Open Question 1) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Task IDs above are provisional — planner assigns final plan/task numbering; this table's row
count and requirement coverage is the binding contract, not the exact IDs.*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_cross_sectional_spread_tracker.py` — new file: decile split,
      turnover-across-run-boundary, cost-hurdle sweep, `--evaluate-gate` grouping,
      `--evaluate-attribution` (Gate 2) — pure-function tests, no live DB (mirrors
      `test_counterfactual_tracker.py`'s shape per RESEARCH.md)
- [ ] `tests/integration/` — new test(s) for incremental watermark scoping and the migration's
      hypertable creation, tagged `requires_db`
- [ ] No new test framework install needed — pytest/pytest-asyncio already configured
      (RESEARCH.md's Environment Availability confirms this)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|--------------------|
| Live Validation Gate 1 verdict over the real, accumulating OOS `construction_spreads` population | Phase goal (turn T3 into a real, monitored construction) | Requires actual persisted rows across real calendar time — a unit test can prove the gate-evaluation *code* is correct, but cannot substitute for the real measurement the phase's goal is about | Run `services/cross_sectional_spread_tracker.py --evaluate-gate` against the live DB after the backfill has populated `construction_spreads`; confirm `ci_lower > 0` and the verdict is logged, matching the pattern already proven in `t3_cross_sectional_long_short_ctf_momentum_check.py`'s output |
| Migration next-free-number verification | Code Examples migration template | Todo 095's documented duplicate-migration-number collision risk — a static test can't catch a race against concurrent sessions | Run `ls production/migrations/ | sort` and confirm the chosen number is genuinely unused immediately before applying, per RESEARCH.md's Assumption A2 |

---

## Validation Sign-Off

- [x] All tasks have automated verify or Wave 0 dependencies (see Per-Task Verification Map)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (decile split, turnover, cost-hurdle, evaluate-gate,
      attribution-honesty, incremental watermark, migration schema)
- [x] No watch-mode flags (`-x` fail-fast, no `--watch`)
- [x] Feedback latency < 60s for unit-level sampling
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
