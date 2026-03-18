---
phase: 36
slug: microstructure-plugins
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-18
---

# Phase 36 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | `pytest.ini` / `pyproject.toml` |
| **Quick run command** | `.venv/bin/pytest tests/unit/ -v -x` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -v` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/ -v -x`
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 36-W0-01 | Wave 0 | 0 | OFI-01 | unit | `.venv/bin/pytest tests/unit/test_ofi_plugin.py -v` | ❌ W0 | ⬜ pending |
| 36-W0-02 | Wave 0 | 0 | CVD-01 | unit | `.venv/bin/pytest tests/unit/test_cvd_plugin.py -v` | ❌ W0 | ⬜ pending |
| 36-W0-03 | Wave 0 | 0 | OFI-03 | unit | `.venv/bin/pytest tests/unit/test_i7_microstructure.py -v` | ❌ W0 | ⬜ pending |
| 36-01-01 | 01 | 1 | OFI-01 | unit | `.venv/bin/pytest tests/unit/test_ofi_plugin.py -v` | ❌ W0 | ⬜ pending |
| 36-01-02 | 01 | 1 | OFI-02 | unit | `.venv/bin/pytest tests/unit/test_ofi_plugin.py::test_ofi_ewma -v` | ❌ W0 | ⬜ pending |
| 36-01-03 | 01 | 1 | OFI-01 | unit | `.venv/bin/pytest tests/unit/test_ofi_plugin.py::test_proxy_fallback -v` | ❌ W0 | ⬜ pending |
| 36-02-01 | 02 | 1 | CVD-01 | unit | `.venv/bin/pytest tests/unit/test_cvd_plugin.py -v` | ❌ W0 | ⬜ pending |
| 36-02-02 | 02 | 1 | CVD-02 | unit | `.venv/bin/pytest tests/unit/test_cvd_plugin.py::test_cvd_slope -v` | ❌ W0 | ⬜ pending |
| 36-03-01 | 03 | 2 | OFI-03 | unit | `.venv/bin/pytest tests/unit/test_i7_microstructure.py::test_ofi_continuation -v` | ❌ W0 | ⬜ pending |
| 36-03-02 | 03 | 2 | OFI-03 | unit | `.venv/bin/pytest tests/unit/test_i7_microstructure.py::test_ofi_divergence -v` | ❌ W0 | ⬜ pending |
| 36-03-03 | 03 | 2 | OFI-03 | unit | `.venv/bin/pytest tests/unit/test_i7_microstructure.py::test_ofi_spike -v` | ❌ W0 | ⬜ pending |
| 36-04-01 | 04 | 2 | CVD-02 | unit | `.venv/bin/pytest tests/unit/test_i7_microstructure.py::test_cvd_divergence -v` | ❌ W0 | ⬜ pending |
| 36-04-02 | 04 | 2 | CVD-02 | unit | `.venv/bin/pytest tests/unit/test_i7_microstructure.py::test_cvd_spike -v` | ❌ W0 | ⬜ pending |
| 36-04-03 | 04 | 2 | CVD-02 | unit | `.venv/bin/pytest tests/unit/test_i7_microstructure.py::test_delta_exhaustion -v` | ❌ W0 | ⬜ pending |
| 36-05-01 | 05 | 2 | CVD-02 | unit | `.venv/bin/pytest tests/unit/test_i7_microstructure.py::test_dual_divergence -v` | ❌ W0 | ⬜ pending |
| 36-06-01 | 06 | 3 | OFI-01,OFI-02,OFI-03,CVD-01,CVD-02 | unit | `.venv/bin/pytest tests/unit/ -v` | ✅ | ⬜ pending |
| 36-06-02 | 06 | 3 | OFI-01 | manual | Replay ES 1m + check `intelligence_features` for OFI fields | n/a | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_ofi_plugin.py` — stubs for OFI-01, OFI-02 (OFIPlugin compute_full, compute_next, proxy fallback, ofi_variant field)
- [ ] `tests/unit/test_cvd_plugin.py` — stubs for CVD-01, CVD-02 (CVDPlugin compute_full, compute_next, cvd_slope_5bar, cvd_divergence)
- [ ] `tests/unit/test_i7_microstructure.py` — stubs for OFI-03 + CVD-02 (all 7 I7 plugins: fire conditions, no_signal paths, regime_type)
- [ ] Update TIER_I7 count assertion in existing tests (28 → 35)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `intelligence_features` rows contain non-NULL OFI/CVD fields after live run | OFI-01, CVD-01 | Requires live indicator_service with real bars | Restart indicator_service, wait 5 min, `SELECT ofi_ewma_20, cvd FROM intelligence_features WHERE symbol='ES' ORDER BY ts DESC LIMIT 5` |
| Both plugins fire at least once in 1-week ES 1m replay | OFI-03, CVD-02 | Requires historical replay infrastructure | Run pipeline_reset.py replay, query `signal_ledger WHERE setup_type IN ('trad_OrderFlowImbalance','trad_CVDDivergence')` |
| `trad_DualDivergence` fires with `is_shadow=True` | CVD-02 | Shadow mode requires live signal_ledger inspection | Check `signal_ledger WHERE setup_type='trad_DualDivergence' AND is_shadow=TRUE` after replay |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
