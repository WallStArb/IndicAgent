---
phase: 12
slug: signal-integrity
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-04
---

# Phase 12 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest with asyncio-mode=auto |
| **Config file** | `pytest.ini` (project root) |
| **Quick run command** | `.venv/bin/pytest tests/unit/intelligence/test_aggregator.py tests/unit/intelligence/test_i7_registration.py tests/unit/intelligence/test_signal_ledger.py -v -m unit` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -v -m unit` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run quick run command above
- **After every plan wave:** Run full suite command
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 12-01-01 | 01 | 1 | SIGINT-01 | unit | `.venv/bin/pytest tests/unit/intelligence/test_i7_registration.py -v` | ❌ W0 | ⬜ pending |
| 12-01-02 | 01 | 1 | SIGINT-01 | unit | `.venv/bin/pytest tests/unit/intelligence/test_aggregator.py -k "regime" -v` | ✅ | ⬜ pending |
| 12-01-03 | 01 | 1 | SIGINT-02 | unit | `.venv/bin/pytest tests/unit/intelligence/test_aggregator.py -k "prob" -v` | ✅ | ⬜ pending |
| 12-01-04 | 01 | 1 | SIGINT-03 | unit | `.venv/bin/pytest tests/unit/intelligence/test_aggregator.py -k "duration" -v` | ✅ | ⬜ pending |
| 12-01-05 | 01 | 1 | SIGINT-04 | unit | `.venv/bin/pytest tests/unit/intelligence/test_aggregator.py -k "cache" -v` | ❌ W0 | ⬜ pending |
| 12-01-06 | 01 | 2 | SIGINT-05 | unit | `.venv/bin/pytest tests/unit/intelligence/test_aggregator.py -k "shadow" -v` | ❌ W0 | ⬜ pending |
| 12-01-07 | 01 | 2 | SIGINT-05 | unit | `.venv/bin/pytest tests/unit/intelligence/test_signal_ledger.py -k "ledger" -v` | ❌ W0 | ⬜ pending |
| 12-01-08 | 01 | 2 | SIGINT-05 | unit | `.venv/bin/pytest tests/unit/intelligence/test_signal_ledger.py -k "active" -v` | ✅ | ⬜ pending |
| 12-01-09 | 01 | 3 | SIGINT-05 | unit | `.venv/bin/pytest tests/unit/intelligence/test_lifecycle_shadow.py -v` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/intelligence/test_i7_registration.py` — add test: all 17 I7 plugins have `regime_type` attribute with valid value (`"trend"`, `"mean_reversion"`, or `"any"`)
- [ ] `tests/unit/intelligence/test_aggregator.py` — add `TestShadowSignals` class covering: suppressed signals in `all_ranked`, `regime_eligible=False` flag, `suppression_reason` values, shadow signals have direction/entry/stop populated
- [ ] `tests/unit/intelligence/test_signal_ledger.py` — add test: `build_ledger_entries` with regime_suppressed signals writes `status='regime_suppressed'`
- [ ] `tests/unit/intelligence/test_lifecycle_shadow.py` — new file: shadow signal virtual-activation (no zone check), MAE/MFE tracking from bar 0, status stays `regime_suppressed` until TTL

*Existing test infrastructure covers pytest config, asyncio, and fixtures — no framework install needed.*

---

## Existing Tests Requiring Updates

| File | Test | Change Required |
|------|------|----------------|
| `tests/unit/intelligence/test_aggregator.py` | `test_gate_bypassed_when_regime_prob_low` | Change probe value from 0.50 to 0.54 (below new threshold 0.60) |
| `tests/unit/intelligence/test_aggregator.py` | `test_gate_bypassed_when_regime_duration_short` | Change duration from 2 to 4 (below new threshold 5) |
| `tests/unit/intelligence/test_aggregator.py` | All tests importing `REGIME_ELIGIBILITY` | Remove import (dict deleted); use `_REGIME_PROB_MIN` / `_REGIME_DUR_MIN` |
| `tests/unit/intelligence/test_signal_ledger.py` | `TestGetActiveSignals.test_returns_entries` | Add `regime_suppressed` to expected returnable statuses |

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Shadow signals visible in signal_ledger with regime_suppressed status | SIGINT-05 | Requires live infrastructure | After service restart, check DB: `SELECT status, COUNT(*) FROM signal_ledger GROUP BY status` — expect `regime_suppressed` rows |
| Regime cache populated from higher-TF streams | SIGINT-04 | Live Redis stream data needed | Check service logs for "regime_cache updated" from 5m/15m events while 1m signals fire |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
