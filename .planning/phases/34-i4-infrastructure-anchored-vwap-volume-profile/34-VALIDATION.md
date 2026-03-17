---
phase: 34
slug: i4-infrastructure-anchored-vwap-volume-profile
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-17
---

# Phase 34 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing) |
| **Config file** | `pytest.ini` (project root) |
| **Quick run command** | `.venv/bin/pytest tests/unit/intelligence/ -x -q` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -v` |
| **Estimated runtime** | ~30 seconds (unit only) |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/intelligence/ -x -q`
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 34-01-01 | 01 | 1 | VWAP-01 | unit | `.venv/bin/pytest tests/unit/intelligence/context/test_anchored_vwap.py -x` | ❌ Wave 0 | ⬜ pending |
| 34-01-02 | 01 | 1 | VWAP-01 | unit | `.venv/bin/pytest tests/unit/intelligence/test_plugin_registry.py -x` | ✅ existing | ⬜ pending |
| 34-01-03 | 01 | 1 | VWAP-01 | unit | `.venv/bin/pytest tests/unit/intelligence/test_i4_new_plugins.py -x` | ✅ extend | ⬜ pending |
| 34-02-01 | 02 | 1 | VOL-01 | unit | `.venv/bin/pytest tests/unit/intelligence/context/test_volume_profile.py -x` | ❌ Wave 0 | ⬜ pending |
| 34-02-02 | 02 | 1 | VOL-01 | unit | `.venv/bin/pytest tests/unit/intelligence/context/test_volume_profile.py::test_poc_value_area -x` | ❌ Wave 0 | ⬜ pending |
| 34-03-01 | 03 | 2 | VWAP-02 | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_anchored_vwap_reversion.py -x` | ❌ Wave 0 | ⬜ pending |
| 34-03-02 | 03 | 2 | VWAP-02 | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_vwap_reclaim.py -x` | ❌ Wave 0 | ⬜ pending |
| 34-03-03 | 03 | 2 | VOL-02 | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_poc_rejection.py -x` | ❌ Wave 0 | ⬜ pending |
| 34-03-04 | 03 | 2 | VOL-02 | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_hvn_rejection.py -x` | ❌ Wave 0 | ⬜ pending |
| 34-03-05 | 03 | 2 | VOL-02 | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_lvn_breakout.py -x` | ❌ Wave 0 | ⬜ pending |
| 34-04-01 | 03 | 2 | VWAP-02, VOL-02 | unit | `.venv/bin/pytest tests/unit/intelligence/test_i7_registration.py -x` | ✅ update counts | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/intelligence/context/test_anchored_vwap.py` — stubs for VWAP-01 (migrated plugin + new I4 fields)
- [ ] `tests/unit/intelligence/context/test_volume_profile.py` — stubs for VOL-01 (migrated plugin + POC/VAH/VAL/dual-track)
- [ ] `tests/unit/intelligence/trading/test_anchored_vwap_reversion.py` — stubs for VWAP-02
- [ ] `tests/unit/intelligence/trading/test_vwap_reclaim.py` — stubs for VWAP-02
- [ ] `tests/unit/intelligence/trading/test_poc_rejection.py` — stubs for VOL-02
- [ ] `tests/unit/intelligence/trading/test_hvn_rejection.py` — stubs for VOL-02
- [ ] `tests/unit/intelligence/trading/test_lvn_breakout.py` — stubs for VOL-02

Existing tests to UPDATE (not create):
- `tests/unit/intelligence/test_i7_registration.py` — update count 23→28, total 106→111, add 5 plugin names
- `tests/unit/intelligence/test_i4_new_plugins.py` — add AVWAP/VP migration coverage
- `tests/unit/intelligence/test_structure_plugins.py` — remove VWAP fields from I3 coverage
- `tests/unit/intelligence/test_pattern_plugins.py` — remove VP fields from I5 coverage

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `intelligence_features` rows contain non-NULL `avwap_session`, `avwap_swing`, `avwap_deviation_pct`, `poc_price`, `vah`, `val` for ES/NQ 1m | VWAP-01, VOL-01 | Requires live pipeline + DB query | `docker exec timescaledb psql -U postgres -d indicagent -c "SELECT avwap_session, poc_price, vah, val FROM intelligence_features WHERE symbol='ES' AND timeframe='1m' ORDER BY ts DESC LIMIT 1;"` |
| `trad_AnchoredVWAPReversion` fires only with correct gate (sigma >1.5, regime==0, hurst <0.55) with regime/hurst values logged | VWAP-02 | Requires live signal replay | Run 1-week replay, query `signal_ledger` for `setup_name='trad_AnchoredVWAPReversion'`, verify `metadata` contains `hmm_regime` and `hurst_exponent` fields |
| `trad_VolumeProfileReaction` fires in all three variants (POC, HVN, LVN) across 1-week replay | VOL-02 | Requires live replay to confirm all variants hit | `SELECT DISTINCT metadata->>'variant' FROM signal_ledger WHERE setup_name LIKE 'trad_%Rejection' OR setup_name='trad_LVNBreakout' ORDER BY 1` — expect POC, HVN, LVN labels |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
