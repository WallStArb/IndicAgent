---
phase: 33
slug: five-new-i7-signal-plugins
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-17
---

# Phase 33 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing) |
| **Config file** | `pyproject.toml` — existing |
| **Quick run command** | `.venv/bin/pytest tests/unit/intelligence/trading/ -v -x` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -v` |
| **Estimated runtime** | ~15 seconds (unit only) |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/intelligence/trading/ -v -x`
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 33-01-01 | 01 | 0 | PLUG-01 | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_failed_breakout.py -x` | ❌ W0 | ⬜ pending |
| 33-01-02 | 01 | 0 | PLUG-02 | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_orb15.py -x` | ❌ W0 | ⬜ pending |
| 33-01-03 | 01 | 0 | PLUG-02 | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_orb30.py -x` | ❌ W0 | ⬜ pending |
| 33-01-04 | 01 | 0 | PLUG-03 | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_prev_day_level_test.py -x` | ❌ W0 | ⬜ pending |
| 33-01-05 | 01 | 0 | PLUG-04 | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_second_leg_continuation.py -x` | ❌ W0 | ⬜ pending |
| 33-01-06 | 01 | 0 | PLUG-05 | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_vcp.py -x` | ❌ W0 | ⬜ pending |
| 33-02-01 | 02 | 1 | PLUG-01 | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_failed_breakout.py -x` | ❌ W0 | ⬜ pending |
| 33-02-02 | 02 | 1 | PLUG-02 | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_orb15.py tests/unit/intelligence/trading/test_orb30.py -x` | ❌ W0 | ⬜ pending |
| 33-02-03 | 02 | 1 | PLUG-03 | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_prev_day_level_test.py -x` | ❌ W0 | ⬜ pending |
| 33-02-04 | 02 | 1 | PLUG-04 | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_second_leg_continuation.py -x` | ❌ W0 | ⬜ pending |
| 33-02-05 | 02 | 1 | PLUG-05 | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_vcp.py -x` | ❌ W0 | ⬜ pending |
| 33-03-01 | 03 | 2 | ALL | integration | `.venv/bin/pytest tests/unit/intelligence/test_correctness_audit.py -x` | ✅ existing | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/intelligence/trading/test_failed_breakout.py` — stubs for PLUG-01 (BOS gate, 3-bar reversal window, no-signal cases)
- [ ] `tests/unit/intelligence/trading/test_orb15.py` — stubs for PLUG-02 ORB15 (range accumulation 09:30–09:45, breakout gate, session window gate)
- [ ] `tests/unit/intelligence/trading/test_orb30.py` — stubs for PLUG-02 ORB30 (range accumulation 09:30–10:00, breakout gate, session window gate)
- [ ] `tests/unit/intelligence/trading/test_prev_day_level_test.py` — stubs for PLUG-03 (fade variant, continuation variant, no prior session data)
- [ ] `tests/unit/intelligence/trading/test_second_leg_continuation.py` — stubs for PLUG-04 (Fib zone gate, leg amplitude filter, ranging regime rejection)
- [ ] `tests/unit/intelligence/trading/test_vcp.py` — stubs for PLUG-05 (3+ contractions + volume, session reset, hmm_regime_prob gate)

*(Framework and conftest already exist — `tests/unit/intelligence/helpers.py` provides `make_ohlcv()` for all tests. No new framework install needed.)*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| All 6 plugins fire at least once on ES/NQ 1m in 7-day replay | ALL (success criteria 2) | Requires live replay infrastructure + signal_ledger query | Run `pipeline_reset.py --symbols ES,NQ --days 7` then `SELECT setup_plugin, COUNT(*) FROM signal_ledger WHERE computed_at > now() - interval '7 days' GROUP BY setup_plugin` — confirm non-zero rows for all 6 plugin names |
| trad_ORB15/30 fire only between 09:30 and 11:30 ET | PLUG-02 (success criteria 3) | Time-gating requires replay data with real timestamps | Query `signal_ledger WHERE setup_plugin LIKE 'trad_ORB%'` and verify all `computed_at` values fall in ET 09:30–11:30 window |
| trad_VCP logs contraction count in signal metadata | PLUG-05 (success criteria 5) | Requires replay signals in signal_ledger | `SELECT metadata FROM signal_ledger WHERE setup_plugin = 'trad_VCP' LIMIT 5` — verify `contraction_count` key present with value ≥ 3 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
