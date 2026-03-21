---
phase: 44
slug: i7-dag-refactor
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-20
---

# Phase 44 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | `pytest.ini` / `pyproject.toml` |
| **Quick run command** | `.venv/bin/pytest tests/unit/ -x -q` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -v` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/ -x -q`
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 44-01-01 | 01 | 1 | DAG-01 | unit | `.venv/bin/pytest tests/unit/test_base_i7_plugin.py -v` | ❌ W0 | ⬜ pending |
| 44-01-02 | 01 | 1 | DAG-01 | unit | `.venv/bin/pytest tests/unit/test_atr_utils.py -v` | ❌ W0 | ⬜ pending |
| 44-01-03 | 01 | 1 | DAG-02 | unit | `.venv/bin/pytest tests/unit/test_position_utils.py -v` | ❌ W0 | ⬜ pending |
| 44-01-04 | 01 | 1 | DAG-01 | integration | `.venv/bin/pytest tests/unit/ -k "i7_plugin" -v` | ❌ W0 | ⬜ pending |
| 44-02-01 | 02 | 1 | DAG-03 | unit | `.venv/bin/pytest tests/unit/test_confidence_utils.py -v` | ❌ W0 | ⬜ pending |
| 44-02-02 | 02 | 2 | DAG-03 | grep | `grep -r "compose_confidence" src/intelligence/trading/` | ✅ | ⬜ pending |
| 44-03-01 | 03 | 1 | DAG-04 | unit | `.venv/bin/pytest tests/unit/test_validate_tier.py -v` | ❌ W0 | ⬜ pending |
| 44-03-02 | 03 | 2 | DAG-04 | unit | `.venv/bin/pytest tests/unit/intelligence/ -k "cross_timeframe or confluence" -v` | ❌ W0 | ⬜ pending |
| 44-04-01 | 04 | 1 | DAG-01 | unit | `.venv/bin/pytest tests/unit/test_common_utils.py -v` | ❌ W0 | ⬜ pending |
| 44-04-02 | 04 | 2 | DAG-02 | unit | `.venv/bin/pytest tests/unit/ -k "ofi" -v` | ✅ | ⬜ pending |
| 44-04-03 | 04 | 2 | DAG-02 | unit | `.venv/bin/pytest tests/unit/test_signal_schema.py -v` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_base_i7_plugin.py` — stubs for BaseI7Plugin interface (DAG-01)
- [ ] `tests/unit/test_atr_utils.py` — stubs for calculate_atr() (DAG-01)
- [ ] `tests/unit/test_position_utils.py` — stubs for build_stops_targets(), signal_type_for_direction() (DAG-02)
- [ ] `tests/unit/test_confidence_utils.py` — stubs for compose_confidence() floor/ceil contract (DAG-03)
- [ ] `tests/unit/test_validate_tier.py` — hard-crash test for missing regime_type (DAG-04)
- [ ] `tests/unit/intelligence/test_confluence_alignment.py` — stubs for decomposed cross_timeframe (DAG-04)
- [ ] `tests/unit/test_common_utils.py` — stubs for promoted is_num, crossover_detect, etc.
- [ ] `tests/unit/test_signal_schema.py` — stubs for make_signal() and validate_signal() (DAG-02)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Zero signal behavior change | DAG-01–04 | Requires live Redpanda + services | Start market_analysis_service + signal_generator_service; compare signal output before/after refactor for same bar data |
| Plugin count = 36 | DAG-01 | Cannot grep-count reliably with inheritance | Count TIER_I7 in register_plugins.py manually; confirm BaseI7Plugin covers all 36 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
