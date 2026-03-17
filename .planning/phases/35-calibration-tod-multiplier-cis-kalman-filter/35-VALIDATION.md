---
phase: 35
slug: calibration-tod-multiplier-cis-kalman-filter
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-17
---

# Phase 35 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (`.venv/bin/pytest`) |
| **Config file** | `pytest.ini` / `pyproject.toml` (project root) |
| **Quick run command** | `.venv/bin/pytest tests/unit/intelligence/test_confidence_calibrator.py tests/unit/service_tests/test_signal_generator_calibration.py -x -q` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -v` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/intelligence/test_confidence_calibrator.py tests/unit/service_tests/test_signal_generator_calibration.py -x -q`
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 35-01-01 | 01 | 0 | CAL-01, CAL-02, KAL-02 | wave0 | N/A — file creation | ❌ W0 | ⬜ pending |
| 35-01-02 | 01 | 0 | KAL-01 | wave0 | N/A — config creation | ❌ W0 | ⬜ pending |
| 35-02-01 | 02 | 1 | CAL-01, CAL-02 | unit | `.venv/bin/pytest tests/unit/intelligence/test_confidence_calibrator.py -x -q` | ❌ W0 | ⬜ pending |
| 35-02-02 | 02 | 1 | CAL-02 | unit | `.venv/bin/pytest tests/unit/intelligence/test_confidence_calibrator.py -k "weight_update" -x` | ❌ W0 | ⬜ pending |
| 35-03-01 | 03 | 1 | KAL-02, CAL-02 | unit | `.venv/bin/pytest tests/unit/intelligence/test_confidence_calibrator.py::test_calibration_table_schema -x` | ❌ W0 | ⬜ pending |
| 35-04-01 | 04 | 2 | TOD-01, TOD-02 | unit | `.venv/bin/pytest tests/unit/service_tests/test_signal_generator_calibration.py::test_tod_bayesian_smoothing -x` | ❌ W0 | ⬜ pending |
| 35-04-02 | 04 | 2 | TOD-02 | unit | `.venv/bin/pytest tests/unit/service_tests/test_signal_generator_calibration.py::test_tod_multiplier_clamp -x` | ❌ W0 | ⬜ pending |
| 35-05-01 | 05 | 2 | KAL-01 | unit | `.venv/bin/pytest tests/unit/service_tests/test_signal_generator_calibration.py::test_cis_kalman_convergence -x` | ❌ W0 | ⬜ pending |
| 35-05-02 | 05 | 2 | KAL-02 | unit | `.venv/bin/pytest tests/unit/service_tests/test_signal_generator_calibration.py::test_shadow_fire_condition -x` | ❌ W0 | ⬜ pending |
| 35-06-01 | 06 | 3 | CAL-03 | unit | `.venv/bin/pytest tests/unit/intelligence/test_aggregator.py -k calibrated -x` | ❌ W0 | ⬜ pending |
| 35-07-01 | 07 | 3 | CAL-02, CAL-03 | unit | `.venv/bin/pytest tests/unit/ -v` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/intelligence/test_confidence_calibrator.py` — stubs for CAL-01, CAL-02
- [ ] `tests/unit/intelligence/ml/__init__.py` — package marker for new `ml/` subdirectory
- [ ] `tests/unit/service_tests/test_signal_generator_calibration.py` — stubs for TOD-01, TOD-02, KAL-01, KAL-02
- [ ] `config/kalman_parameters.json` — must be created (KalmanTrendPlugin falls back to hardcoded defaults without it; CIS Kalman needs `cis_kalman` section)
- [ ] `production/migrations/038_calibration_fields.sql` — `confidence_calibration` table + 3 `signal_ledger` columns (`raw_cis_score`, `filtered_cis_score`, `calibrated_confidence`)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| TOD multiplier varies by hour in logs | TOD-02 | Requires live signal_generator running with real market hours | `grep "tod_multiplier" logs/signal_generator.log` — check 09:30 vs 12:00 ET differ |
| Shadow fire condition suppresses marginal signals | KAL-02 | Requires N≥30 suppressed signals across regime types | Monitor `signal_ledger` for `is_shadow=TRUE` rows after deployment |
| Calibration batch job coexists with weight_updater | CAL-02 | Requires 30-min timer to fire | Check logs/weight_updater.log for both `weight_update` and `calibration_update` entries without errors |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
