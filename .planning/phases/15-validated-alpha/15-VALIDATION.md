---
phase: 15
slug: validated-alpha
status: ready
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-08
---

# Phase 15 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | `pytest.ini` (existing) |
| **Quick run command** | `.venv/bin/pytest tests/unit/scripts/test_validate_alpha.py tests/unit/intelligence/test_ac_oscillator.py tests/unit/intelligence/composites/test_derivative_oscillator.py tests/unit/intelligence/test_candlestick_tier1.py -v -x` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -v` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run quick run command covering that task's test file
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 15-01-01 | 01 | 1 | ALPHA-01 | unit | `.venv/bin/pytest tests/unit/scripts/test_validate_alpha.py::test_gate_logic -x` | ❌ W0 | ⬜ pending |
| 15-01-02 | 01 | 1 | ALPHA-01 | unit | `.venv/bin/pytest tests/unit/scripts/test_validate_alpha.py::test_gate_fails_low_n -x` | ❌ W0 | ⬜ pending |
| 15-01-03 | 01 | 1 | ALPHA-01 | unit | `.venv/bin/pytest tests/unit/scripts/test_validate_alpha.py::test_promote_blocked_on_fail -x` | ❌ W0 | ⬜ pending |
| 15-01-04 | 01 | 1 | ALPHA-01 | unit | `.venv/bin/pytest tests/unit/scripts/test_validate_alpha.py::test_auto_backfill_triggered -x` | ❌ W0 | ⬜ pending |
| 15-01-05 | 01 | 1 | ALPHA-01 | unit | `.venv/bin/pytest tests/unit/scripts/test_validate_alpha.py::test_report_written -x` | ❌ W0 | ⬜ pending |
| 15-01-06 | 01 | 1 | ALPHA-01 | unit | `.venv/bin/pytest tests/unit/scripts/test_validate_alpha.py::test_forward_return_alignment -x` | ❌ W0 | ⬜ pending |
| 15-02-01 | 02 | 2 | ALPHA-02 | unit | `.venv/bin/pytest tests/unit/intelligence/composites/test_derivative_oscillator.py::test_outputs_present -x` | ❌ W0 | ⬜ pending |
| 15-02-02 | 02 | 2 | ALPHA-02 | unit | `.venv/bin/pytest tests/unit/intelligence/composites/test_derivative_oscillator.py::test_missing_rsi -x` | ❌ W0 | ⬜ pending |
| 15-02-03 | 02 | 2 | ALPHA-02 | unit | `.venv/bin/pytest tests/unit/intelligence/composites/test_derivative_oscillator.py::test_bullish_cross -x` | ❌ W0 | ⬜ pending |
| 15-02-04 | 02 | 2 | ALPHA-02 | unit | `.venv/bin/pytest tests/unit/intelligence/test_i2_registration.py -x` | ✅ (extend) | ⬜ pending |
| 15-03-01 | 03 | 2 | ALPHA-03 | unit | `.venv/bin/pytest tests/unit/intelligence/test_candlestick_tier1.py::test_three_white_soldiers -x` | ❌ W0 | ⬜ pending |
| 15-03-02 | 03 | 2 | ALPHA-03 | unit | `.venv/bin/pytest tests/unit/intelligence/test_candlestick_tier1.py::test_three_black_crows -x` | ❌ W0 | ⬜ pending |
| 15-03-03 | 03 | 2 | ALPHA-03 | unit | `.venv/bin/pytest tests/unit/intelligence/test_candlestick_tier1.py::test_morning_star -x` | ❌ W0 | ⬜ pending |
| 15-03-04 | 03 | 2 | ALPHA-03 | unit | `.venv/bin/pytest tests/unit/intelligence/test_candlestick_tier1.py::test_evening_star -x` | ❌ W0 | ⬜ pending |
| 15-03-05 | 03 | 2 | ALPHA-03 | unit | `.venv/bin/pytest tests/unit/intelligence/test_candlestick_tier1.py::test_three_inside_up -x` | ❌ W0 | ⬜ pending |
| 15-03-06 | 03 | 2 | ALPHA-03 | unit | `.venv/bin/pytest tests/unit/intelligence/test_candlestick_tier1.py::test_harami_cross -x` | ❌ W0 | ⬜ pending |
| 15-03-07 | 03 | 2 | ALPHA-03 | unit | `.venv/bin/pytest tests/unit/intelligence/test_candlestick_tier1.py::test_min_lookback_guard -x` | ❌ W0 | ⬜ pending |
| 15-03-08 | 03 | 2 | ALPHA-03 | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_candlestick_pattern_setup.py::test_no_new_pattern_reads -x` | ✅ (extend) | ⬜ pending |
| 15-04-01 | 04 | 2 | ALPHA-04 | unit | `.venv/bin/pytest tests/unit/intelligence/test_i2_plugins.py::TestMACDEvents -x` | ✅ (extend) | ⬜ pending |
| 15-04-02 | 04 | 2 | ALPHA-04 | unit | `.venv/bin/pytest tests/unit/intelligence/test_i2_plugins.py::TestMACDEvents::test_hist_contracting -x` | ✅ (extend) | ⬜ pending |
| 15-04-03 | 04 | 2 | ALPHA-04 | unit | `.venv/bin/pytest tests/unit/intelligence/test_i2_schema.py -x` | ✅ (extend) | ⬜ pending |
| 15-05-01 | 05 | 2 | ALPHA-05 | unit | `.venv/bin/pytest tests/unit/intelligence/test_ac_oscillator.py::test_outputs_present -x` | ❌ W0 | ⬜ pending |
| 15-05-02 | 05 | 2 | ALPHA-05 | unit | `.venv/bin/pytest tests/unit/intelligence/test_ac_oscillator.py::test_formula_correctness -x` | ❌ W0 | ⬜ pending |
| 15-05-03 | 05 | 2 | ALPHA-05 | unit | `.venv/bin/pytest tests/unit/intelligence/test_ac_oscillator.py::test_insufficient_bars_39 -x` | ❌ W0 | ⬜ pending |
| 15-05-04 | 05 | 2 | ALPHA-05 | unit | `.venv/bin/pytest tests/unit/intelligence/test_plugin_registry.py -x` | ✅ (extend) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/scripts/test_validate_alpha.py` — stubs for ALPHA-01 (gate logic, report writing, forward return alignment, auto-backfill trigger, promote block on failure)
- [ ] `tests/unit/intelligence/composites/test_derivative_oscillator.py` — stubs for ALPHA-02 (outputs present, missing RSI guard, crossover detection, EMA warmup)
- [ ] `tests/unit/intelligence/test_candlestick_tier1.py` — stubs for ALPHA-03 (all 10 patterns including evening_star, min_lookback guard, no-pattern baseline)
- [ ] `tests/unit/intelligence/test_ac_oscillator.py` — stubs for ALPHA-05 (formula correctness, insufficient bars guard, output types)
- [ ] `docs/validation/` directory — must exist before first `--promote` run; create in Plan 1 Wave 0

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `--promote` patches `register_plugins.py` correctly and service starts without crash | ALPHA-01 | Requires live service restart + `registry.validate_tier()` check at startup | After `--promote` run: `sudo systemctl restart indicagent-indicator indicagent-market-analysis` and check `journalctl -u indicagent-indicator -n 20` for no ValueError |
| Validation report JSON written to `docs/validation/` after first real `--promote` | ALPHA-01 | Requires actual DB connection | Run `python production/scripts/validate_alpha.py --plugin <name> --days 90` against live DB and verify file created |
| New candlestick patterns appear in `intelligence_features.i5` JSONB after replay | ALPHA-03 | Requires DB inspection | `docker exec timescaledb psql -U postgres -d indicagent -c "SELECT i5 FROM intelligence_features LIMIT 5"` and verify new fields present |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (all tasks have individual automated commands)
- [x] Wave 0 covers all MISSING references (4 new test files + docs/validation/ directory)
- [x] No watch-mode flags (all commands are single-run pytest invocations)
- [x] Feedback latency < 30s (quick run command targets ~30s; individual task commands < 5s)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved

---

## Wave Structure Confirmation

Plans 02, 03, 04, 05 all declare `wave: 2` and `depends_on: [15-01]` in their frontmatter — they execute in parallel after Plan 01 completes. The wave column in the task table above reflects this: all Plan 02-05 tasks are wave 2. Independent failure isolation: each plan targets a different plugin with no shared files (except register_plugins.py patched only at --promote time, which is sequential by nature).
