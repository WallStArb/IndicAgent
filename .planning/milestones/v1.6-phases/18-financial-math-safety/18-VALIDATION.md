---
phase: 18
slug: financial-math-safety
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-08
---

# Phase 18 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

## Validation Architecture

This phase implements mathematical safety measures that require specific validation approaches:

1. **Epsilon Tolerance (FIN-01, FIN-02):** Verify floating-point comparisons use `math.isclose()` or explicit epsilon with `rel_tol=1e-9`. Validate with property-based tests using pytest to generate edge cases (zero, very small values, very large values).

2. **Magic Number Documentation (FIN-03, FIN-04, FIN-05, FIN-06):** Verify all magic numbers have been extracted as module-level constants with inline comments explaining their derivation and why they work. Verify via code review (grep for bare numeric literals in protected files).

3. **Timeout Configuration (API-01, API-02, API-03, API-04):** Verify Settings exposes `ibkr_timeout_sec` and `llm_timeout_sec` with documented defaults. Verify IBKR provider and LLM providers read these values. Test with integration mocks that simulate delays.

4. **Concurrent Lock Protection (API-05, API-06, API-07):** Verify per-key `asyncio.Lock()` is used for shared dictionary access (`_plugin_states`, `_i1_plugin_states`, `_latest_signals`). Test with concurrent asyncio tasks attempting simultaneous writes.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pytest.ini (existing) |
| **Quick run command** | `.venv/bin/pytest tests/unit/ -v -k "test_float" --tb=short` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -v` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/ -v -k "test_float or test_magic" --tb=short`
- **After every plan wave:** Run full unit suite
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 18-01-01 | 01 | 1 | FIN-01 | unit | `.venv/bin/pytest tests/unit/trading/test_trade_framer.py -v -k "epsilon" --tb=short` | ✅ | ⬜ pending |
| 18-01-02 | 01 | 1 | FIN-02 | unit | `.venv/bin/pytest tests/unit/trading/test_cis_scorer.py -v -k "epsilon" --tb=short` | ✅ | ⬜ pending |
| 18-01-03 | 01 | 1 | FIN-03, FIN-04, FIN-05, FIN-06 | code_review | `grep -E "^EPSILON_|^ATR_|^REGIME_" /home/bg/dev/indicagent/src/intelligence/trading/trade_framer.py | ✅ | ⬜ pending |
| 18-02-01 | 02 | 1 | API-01 | unit | `.venv/bin/python -c "from src.config.settings import Settings; s=Settings(); assert hasattr(s, 'ibkr_timeout_sec'); assert s.ibkr_timeout_sec == 20.0"` | ✅ | ⬜ pending |
| 18-02-02 | 02 | 1 | API-02 | unit | `.venv/bin/python -c "from src.config.settings import Settings; s=Settings(); assert hasattr(s, 'llm_timeout_sec'); assert s.llm_timeout_sec == 60.0"` | ✅ | ⬜ pending |
| 18-03-01 | 03 | 2 | API-03 | integration | `.venv/bin/pytest tests/unit/providers/test_ibkr.py -v -k "timeout" --tb=short` | ✅ | ⬜ pending |
| 18-03-02 | 03 | 2 | API-04 | unit | `.venv/bin/pytest tests/unit/intelligence/test_llm_providers.py -v -k "timeout" --tb=short` | ✅ | ⬜ pending |
| 18-03-03 | 03 | 2 | API-05 | unit | `.venv/bin/pytest tests/unit/services/test_market_analysis_service.py -v -k "lock" --tb=short` | ✅ | ⬜ pending |
| 18-03-04 | 03 | 2 | API-06 | unit | `.venv/bin/pytest tests/unit/services/test_indicator_service.py -v -k "lock" --tb=short` | ✅ | ⬜ pending |
| 18-03-05 | 03 | 2 | API-07 | unit | `.venv/bin/pytest tests/unit/services/test_ai_narrative_service.py -v -k "lock" --tb=short` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

**Existing infrastructure covers all phase requirements.** No Wave 0 setup needed—pytest framework is configured, existing test files exist for modified services, and automated verify commands are in-place.

---

## Manual-Only Verifications

All phase behaviors have automated verification. Manual validation not required.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
