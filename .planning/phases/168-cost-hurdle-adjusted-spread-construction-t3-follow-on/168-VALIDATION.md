---
phase: 168
slug: cost-hurdle-adjusted-spread-construction-t3-follow-on
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-31
---

# Phase 168 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4+ (`pytest-asyncio` 1.1+, `asyncio_mode=auto`) — same as Phase 167 |
| **Config file** | `pytest.ini` (repo root) |
| **Quick run command** | `.venv/bin/pytest tests/unit/test_cross_sectional_spread_tracker.py -x` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -q` |
| **Estimated runtime** | ~30 seconds (quick) / ~5 minutes (full suite) |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/test_cross_sectional_spread_tracker.py -x`
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green, PLUS a live `--evaluate-delta-gate` run producing a real (not mocked) D-04 verdict — mirrors Phase 167-VALIDATION.md's binding rule that a unit-test pass alone does not constitute "the construction is validated."
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 168-01-xx | 01 | 1 | D-01 | — | `hysteresis_legs()` basic stickiness (held symbol survives a small challenger margin) | unit | `pytest tests/unit/test_cross_sectional_spread_tracker.py::test_hysteresis_legs_holds_below_margin -x` | ❌ W0 | ⬜ pending |
| 168-01-xx | 01 | 1 | D-01 | — | `hysteresis_legs()` displaces when margin cleared | unit | `pytest tests/unit/test_cross_sectional_spread_tracker.py::test_hysteresis_legs_displaces_above_margin -x` | ❌ W0 | ⬜ pending |
| 168-01-xx | 01 | 1 | D-01 | T-168-01 | Held symbol absent from current panel force-exits | unit | `pytest tests/unit/test_cross_sectional_spread_tracker.py::test_hysteresis_legs_force_exits_absent_symbol -x` | ❌ W0 | ⬜ pending |
| 168-01-xx | 01 | 1 | D-01 | — | Long/short leg disjointness invariant | unit | `pytest tests/unit/test_cross_sectional_spread_tracker.py::test_hysteresis_legs_no_overlap -x` | ❌ W0 | ⬜ pending |
| 168-02-xx | 02 | 2 | D-02 | T-168-03 | Backfilling cost-gated variant with baseline rows already present does not leak state | integration (requires_db) | `pytest tests/integration/test_cross_sectional_spread_tracker.py::test_backfill_second_construction_name_isolated -x` | ❌ W0 | ⬜ pending |
| 168-03-xx | 03 | 2 | D-04.1 | — | Delta-series construction aligns matching `bar_ts` correctly, feeds `frame_gate_passes` | unit | `pytest tests/unit/test_cross_sectional_spread_tracker.py::test_evaluate_delta_gate_alignment -x` | ❌ W0 | ⬜ pending |
| 168-04-xx | 04 | 3 | D-04.4 | — | New stateful shuffled null produces a coherent per-draw sequential simulation | unit | `pytest tests/unit/test_cross_sectional_spread_tracker.py::test_stateful_shuffled_null_carries_state -x` | ❌ W0 | ⬜ pending |
| 168-04-xx | 04 | 3 | D-04 | — | `--evaluate-delta-gate` live run produces a real verdict artifact | manual/integration | `services/cross_sectional_spread_tracker.py --evaluate-delta-gate` against live DB after both constructions are backfilled | ❌ W0 (manual) | ⬜ pending |
| 168-0x-xx | — | — | T-168-01 | T-168-01 | Malformed/out-of-range hysteresis margin APR value raises `ValueError` at load, not silently clamped | unit | `pytest tests/unit/test_cross_sectional_spread_tracker.py::test_validate_construction_config_rejects_bad_margin -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*
*Exact task IDs are assigned once the planner emits PLAN.md waves — this table anchors the required test surface, not final IDs.*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_cross_sectional_spread_tracker.py` — extend with `hysteresis_legs()` cases (stickiness, displacement, absent-symbol force-exit, no-overlap invariant), delta-series alignment, stateful null, and APR validation rejection
- [ ] `tests/integration/test_cross_sectional_spread_tracker.py` — extend with second-construction-name backfill isolation test
- [ ] No new test framework install needed — pytest/pytest-asyncio already pinned and in active use by Phase 167's own test suite

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| D-04 four-part validation gate verdict (Sharpe-delta CI, gross-spread non-degradation, turnover diagnostic, stateful shuffled null) | D-04 | Requires a live backfill of both `construction_name` partitions over the identical historical window against the real DB — not mockable without defeating the purpose of the gate (same posture as Phase 167-VALIDATION.md) | Run `services/cross_sectional_spread_tracker.py --evaluate-delta-gate` against the live DB after both `ctf_momentum_decile_ls` and `ctf_momentum_decile_ls_cost_gated` are backfilled over the same window; inspect the written verdict artifact in `logs/construction_verdicts/` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
