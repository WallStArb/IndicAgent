---
phase: 23
slug: signal-generator-gate
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-10
---

# Phase 23 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | `pytest.ini` (project root) |
| **Quick run command** | `.venv/bin/pytest tests/unit/service_tests/test_signal_generator_service.py -v` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -v` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run quick run command
- **After every plan wave:** Run full suite command
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 23-01-01 | 01 | 1 | gate-init | unit | `.venv/bin/pytest tests/unit/service_tests/test_signal_generator_service.py -v -k "gate"` | ❌ W0 | ⬜ pending |
| 23-01-02 | 01 | 1 | gate-cooldown | unit | `.venv/bin/pytest tests/unit/service_tests/test_signal_generator_service.py -v -k "cooldown"` | ❌ W0 | ⬜ pending |
| 23-01-03 | 01 | 1 | gate-flip-suppressed | unit | `.venv/bin/pytest tests/unit/service_tests/test_signal_generator_service.py -v -k "flip"` | ❌ W0 | ⬜ pending |
| 23-01-04 | 01 | 1 | gate-flip-allowed | unit | `.venv/bin/pytest tests/unit/service_tests/test_signal_generator_service.py -v -k "resolution"` | ❌ W0 | ⬜ pending |
| 23-02-01 | 02 | 2 | gate-cooldown, gate-flip-suppressed, gate-flip-allowed | unit | `.venv/bin/pytest tests/unit/service_tests/test_signal_generator_service.py -v -k "gate"` | ✅ | ⬜ pending |
| 23-02-02 | 02 | 2 | gate-init (integration) | unit | `.venv/bin/pytest tests/unit/service_tests/test_signal_generator_service.py -v` | ✅ | ⬜ pending |
| 23-03-01 | 03 | 3 | inputspec-cleanup | unit | `.venv/bin/pytest tests/unit/ -v -k "inputspec or i7"` | ✅ | ⬜ pending |
| 23-03-02 | 03 | 3 | 4h-1d-exclusion | grep | `grep -c "4h and 1d intentionally excluded" services/market_analysis_service.py && grep -c "4h and 1d intentionally excluded" services/signal_generator_service.py` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/service_tests/test_signal_generator_service.py` — add stubs for gate cooldown, flip suppression, flip-after-resolution tests
- [ ] Tests must use `ServiceClass.__new__(ServiceClass)` pattern (per CLAUDE.md service test pattern) and manually set `_signal_gate = {}` on instance

*Existing infrastructure covers all other phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live signal deduplication | gate-live | Requires live IBKR feed + 50m warmup | After deploy: check dashboard signal history for same setup repeating every bar; should be suppressed |
| Direction flip blocked in dashboard | flip-live | Requires lifecycle exit event in real pipeline | After deploy: observe no rapid 5m LONG → SHORT flip on same plugin without intervening resolution |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
