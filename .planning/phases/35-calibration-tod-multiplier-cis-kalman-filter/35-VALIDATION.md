---
phase: 35
slug: calibration-tod-multiplier-cis-kalman-filter
status: draft
nyquist_compliant: true
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

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | Status |
|---------|------|------|-------------|-----------|-------------------|--------|
| 35-01-T1 | 01 | 1 | CAL-01, CAL-02 | structural | `python3 -c "from src.intelligence.trading.signal_ledger import LedgerEntry; assert 'raw_cis_score' in LedgerEntry.__dataclass_fields__; assert 'regime_type_at_fire' in LedgerEntry.__dataclass_fields__; print('OK')"` | ⬜ pending |
| 35-01-T2 | 01 | 1 | CAL-01, CAL-02 | unit | `.venv/bin/pytest tests/unit/intelligence/test_confidence_calibrator.py -x -q` | ⬜ pending |
| 35-01-T3 | 01 | 1 | CAL-02 | lint+unit | `.venv/bin/ruff check src/intelligence/weight_updater.py --select E,F && .venv/bin/pytest tests/unit/ -k "weight_updater or calibrat" -x -q` | ⬜ pending |
| 35-02-T1 | 02 | 2 | CAL-03 | structural+unit | `python3 -c "import inspect; from src.intelligence.trading.aggregator import _build_all_ranked; sig=inspect.signature(_build_all_ranked); assert 'calibration_curves' in sig.parameters; print('OK')"` | ⬜ pending |
| 35-02-T2 | 02 | 2 | TOD-01, TOD-02 | unit | `.venv/bin/pytest tests/unit/service_tests/test_signal_generator_calibration.py -x -q` | ⬜ pending |
| 35-03-T1 | 03 | 3 | KAL-01 | structural | `python3 -c "import json; d=json.load(open('config/kalman_parameters.json')); assert 'cis_kalman' in d; print('OK')"` | ⬜ pending |
| 35-03-T2 | 03 | 3 | KAL-01, KAL-02 | unit | `.venv/bin/pytest tests/unit/service_tests/test_signal_generator_calibration.py -x -q` | ⬜ pending |
| 35-03-T3 | 03 | 3 | KAL-02 | build | `cd dashboard && npm run build 2>&1 | tail -3` | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave Structure

| Wave | Plans | Tasks |
|------|-------|-------|
| 1 | 35-01 | DB migration 038 + LedgerEntry (58 fields), confidence_calibrator.py, weight_updater wiring |
| 2 | 35-02 | aggregator calibrated_confidence sort key, service TOD + calibration loops |
| 3 | 35-03 | CIS Kalman filter + shadow fire condition + dashboard trio display |

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| TOD multiplier varies by hour in logs | TOD-02 | Requires live signal_generator running with real market hours | `grep "tod_multiplier" logs/signal_generator.log` — check 09:30 vs 12:00 ET differ |
| Shadow fire condition suppresses marginal signals | KAL-02 | Requires N>=30 suppressed signals across regime types | Monitor `signal_ledger` for `is_shadow=TRUE` rows after deployment |
| Calibration batch job coexists with weight_updater | CAL-02 | Requires 30-min timer to fire | Check logs/weight_updater.log for both `weight_update` and `calibration_update` entries without errors |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify commands that actually fail on incorrect output
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave structure matches actual plans (3 plans, 3 waves)
- [x] No stale plan references (04–07 removed)
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
