---
phase: 44
slug: i7-dag-refactor
status: draft
nyquist_compliant: true
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
| 44-01-01 | 01 | 1 | DAG-01 | unit | `.venv/bin/pytest tests/unit/intelligence/test_plugin_utils.py tests/unit/intelligence/test_atr_utils.py tests/unit/intelligence/test_confidence_utils.py -v` | Plan 01 creates | ⬜ pending |
| 44-01-02 | 01 | 1 | DAG-03 | unit | `.venv/bin/pytest tests/unit/intelligence/test_utils_common.py -v` | Plan 01 creates | ⬜ pending |
| 44-02-01 | 02 | 2 | DAG-01, DAG-02 | grep | `grep -r "from .plugin_utils import" src/intelligence/trading/ \| wc -l` (expect 28+) | ✅ | ⬜ pending |
| 44-02-02 | 02 | 2 | DAG-03 | grep | `grep -r "compose_confidence" src/intelligence/trading/ \| wc -l` (expect 28+) | ✅ | ⬜ pending |
| 44-02-03 | 02 | 2 | DAG-01 | unit | `.venv/bin/pytest tests/unit/intelligence/ -q --tb=short` | ✅ | ⬜ pending |
| 44-03-01 | 03 | 2 | DAG-04 | import | `.venv/bin/python -c "from src.intelligence.confluence.confluence_weights import get_recency_weight; print('OK')"` | Plan 03 creates | ⬜ pending |
| 44-03-02 | 03 | 2 | DAG-04 | unit | `.venv/bin/pytest tests/unit/intelligence/test_cross_timeframe.py -v` | ✅ | ⬜ pending |
| 44-04-01 | 04 | 3 | DAG-01, DAG-02 | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_ofi_plugins.py tests/unit/intelligence/trading/test_cvd_plugins.py -v` | ✅ | ⬜ pending |
| 44-04-02 | 04 | 3 | DAG-02 | grep | `grep -n 'make_signal(' services/signal_generator_service.py && grep -n 'validate_signal(' services/signal_generator_service.py` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Plan 01 tasks are TDD — they create their own test files as part of the task (RED phase writes tests, GREEN phase implements). No separate Wave 0 stubs needed.

- Plan 01 Task 1 creates: `tests/unit/intelligence/test_plugin_utils.py`, `tests/unit/intelligence/test_atr_utils.py`, `tests/unit/intelligence/test_confidence_utils.py`
- Plan 01 Task 2 creates: `tests/unit/intelligence/test_utils_common.py`

All subsequent plans (02, 03, 04) rely on existing test files that already exist in the codebase or are created by their own tasks.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Zero signal behavior change | DAG-01-04 | Requires live Redpanda + services | Start market_analysis_service + signal_generator_service; compare signal output before/after refactor for same bar data |
| Plugin count = 36 | DAG-01 | Automated count may include non-plugin files | `grep -c "'" src/intelligence/register_plugins.py` in TIER_I7 list; confirm 36 entries |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or create tests inline (TDD)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] No separate Wave 0 needed — Plan 01 is TDD, creates its own tests
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** signed-off
