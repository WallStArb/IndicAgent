---
phase: 32
slug: stop-architecture-extended-divergence-stack
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-03-17
---

# Phase 32 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (`.venv/bin/pytest`) |
| **Config file** | none — project root discovery |
| **Quick run command** | `.venv/bin/pytest tests/unit/test_trade_framer.py tests/unit/test_lifecycle_tracker.py tests/unit/test_divergence_stack.py -x -q` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -v` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/ -x -q`
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| SIG-01a | 01 | 1 | SIG-01 | unit | `.venv/bin/pytest tests/unit/test_trade_framer.py -x` | ❌ W0 | ⬜ pending |
| SIG-01b | 01 | 1 | SIG-01 | unit | `.venv/bin/pytest tests/unit/test_trade_framer.py::test_fvg_stop_basis -x` | ❌ W0 | ⬜ pending |
| SIG-02a | 01 | 1 | SIG-02 | unit | `.venv/bin/pytest tests/unit/test_trade_framer.py::test_garch_multiplier -x` | ❌ W0 | ⬜ pending |
| SIG-02b | 01 | 1 | SIG-02 | unit | `.venv/bin/pytest tests/unit/test_trade_framer.py::test_proximity_gate -x` | ❌ W0 | ⬜ pending |
| SIG-03a | 02 | 2 | SIG-03 | unit | `.venv/bin/pytest tests/unit/test_lifecycle_tracker.py::test_chandelier_trailing -x` | ❌ W0 | ⬜ pending |
| SIG-03b | 02 | 2 | SIG-03 | unit | `.venv/bin/pytest tests/unit/test_lifecycle_tracker.py::test_chandelier_monotonic -x` | ❌ W0 | ⬜ pending |
| SIG-04a | 02 | 2 | SIG-04 | unit | `.venv/bin/pytest tests/unit/test_lifecycle_tracker.py::test_staleness_expiry -x` | ❌ W0 | ⬜ pending |
| SIG-04b | 02 | 2 | SIG-04 | unit | `.venv/bin/pytest tests/unit/test_signal_lifecycle_service.py::test_shadow_tracking -x` | ❌ W0 | ⬜ pending |
| SIG-05  | 02 | 2 | SIG-05 | unit | `.venv/bin/pytest tests/unit/test_signal_generator_service.py::test_ttl_constants -x` | ❌ W0 | ⬜ pending |
| DIV-01  | 03 | 3 | DIV-01 | unit | `.venv/bin/pytest tests/unit/test_macd_divergence.py -x` | ❌ W0 | ⬜ pending |
| DIV-02  | 03 | 3 | DIV-02 | unit | `.venv/bin/pytest tests/unit/test_volume_divergence.py::test_obv_outputs -x` | ❌ W0 | ⬜ pending |
| DIV-03  | 03 | 3 | DIV-03 | unit | `.venv/bin/pytest tests/unit/test_cmf_divergence.py -x` | ❌ W0 | ⬜ pending |
| DIV-04a | 03 | 3 | DIV-04 | unit | `.venv/bin/pytest tests/unit/test_divergence_stack.py::test_weighted_score_gate -x` | ❌ W0 | ⬜ pending |
| DIV-04b | 03 | 3 | DIV-04 | unit | `.venv/bin/pytest tests/unit/test_divergence_stack.py::test_always_log -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_trade_framer.py` — stubs for SIG-01/SIG-02: stop_basis label, FVG tier, GARCH multiplier, proximity gate
- [ ] `tests/unit/test_lifecycle_tracker.py` — stubs for SIG-03/SIG-04: Chandelier computation, monotonic tightening, staleness expiry (extend existing if present)
- [ ] `tests/unit/test_signal_lifecycle_service.py` — stub for SIG-04 shadow tracking after condition_expired
- [ ] `tests/unit/test_signal_generator_service.py` — stub for SIG-05 TTL named constants
- [ ] `tests/unit/test_macd_divergence.py` — stubs for DIV-01
- [ ] `tests/unit/test_cmf_divergence.py` — stubs for DIV-03
- [ ] `tests/unit/test_divergence_stack.py` — stubs for DIV-04 (replace AND-gate tests with weighted score tests)
- [ ] Check `tests/unit/test_volume_divergence.py` — extend for DIV-02 obv_div_* outputs

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `stop_basis` appears in live signal_ledger rows | SIG-01 | Requires live signal fire during market hours | `SELECT DISTINCT stop_basis FROM signal_ledger WHERE computed_at > now() - interval '1 hour'` must return all 3 values |
| `trailing_stop_price` JSONB tightens in replay run | SIG-03 | Requires lifecycle replay over multi-bar window | Run historical_backfill.py replay; query `SELECT trailing_stop_price FROM signal_ledger WHERE status='active' LIMIT 5` and verify JSON array grows and prices monotonically tighten |
| `condition_expired` fires after regime flip in replay | SIG-04 | Requires simulated regime flip scenario | Run lifecycle replay; verify `SELECT outcome, staleness_trigger_reason FROM signal_ledger WHERE outcome='condition_expired' LIMIT 5` returns rows |
| `shadow_outcome` populated after condition_expired | SIG-04 | Requires N bars post-expiry to elapse | Query `SELECT shadow_outcome, shadow_mae, shadow_mfe FROM signal_ledger WHERE outcome='condition_expired'` after replay |

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
