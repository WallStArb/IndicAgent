---
phase: 145
slug: stratificationdimension-formalization-planned
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-06
---

# Phase 145 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (project standard, `pytest.ini` at repo root) |
| **Config file** | `pytest.ini` — `testpaths = tests`, `python_files = test_*.py`, `asyncio_mode = auto` |
| **Quick run command** | `.venv/bin/pytest tests/unit/test_stratification_<name>.py -x -q` (per new test file) |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -v` |
| **Estimated runtime** | ~60-120 seconds (full suite, project-standard) |

---

## Sampling Rate

- **After every task commit:** Run the relevant single new test file (`-x -q` fast-fail)
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -v` (full suite)
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~120 seconds

---

## Per-Task Verification Map

No formal `REQUIREMENTS.md` IDs exist for this phase — mapped against CONTEXT.md's decisions
(D-01 through D-07), which function as this phase's real requirements.

| Decision | Behavior | Test Type | Automated Command | File Exists | Status |
|----------|----------|-----------|--------------------|-------------|--------|
| D-01 (row-grain, Option B) | `name` encodes `(dimension, regime_group)` correctly, e.g. `hmm_price_vol__equity` != `hmm_price_vol__rates` | unit | `.venv/bin/pytest tests/unit/test_stratification_contract.py -x -q` | ❌ W0 | ⬜ pending |
| D-03 (BH-FDR across candidate pool) | `apply_bh_fdr` called once per `regime_group`'s cumulative candidate test history, not per-candidate in isolation | unit | `.venv/bin/pytest tests/unit/test_stratification_gates.py -x -q -k fdr` | ❌ W0 | ⬜ pending |
| D-04 (effective-N from transitions) | `effective_n_from_transitions()` returns transitions+1, handles empty/degenerate sequences without crashing | unit | `.venv/bin/pytest tests/unit/test_stratification_gates.py -x -q -k effective_n` | ❌ W0 | ⬜ pending |
| D-05 (acausal-placebo registration gate) | A provider whose `compute()` is deliberately given a future-shifted input fails registration (hard-raise); a causally-correct provider passes | unit | `.venv/bin/pytest tests/unit/test_acausal_placebo_registration.py -x -q` | ❌ W0 | ⬜ pending |
| D-06 (`volatility_pct` pilot, full gate stack) | End-to-end: pilot dimension clears/fails gate 0 → 0.5 → 1 → 2 → FDR, against real 3-5 symbol data | integration (real DB read via `market_data_ohlcv_tradeable`) | `.venv/bin/pytest tests/unit/test_volatility_pct_pilot.py -x -q` (or `tests/integration/` — planner's call) | ❌ W0 | ⬜ pending |
| `ic_engine.py` compatibility (CONTEXT.md code_context note) | Contract's `compute()`/`score()` output shape consumable by code shaped like `_build_regime_passes`'s existing input contract, without modifying `ic_engine.py` | unit | `.venv/bin/pytest tests/unit/test_stratification_contract.py -x -q -k ic_engine_compat` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_stratification_contract.py` — Protocol/ABC conformance + `ic_engine.py` compatibility check
- [ ] `tests/unit/test_stratification_gates.py` — gate 0 (structural pre-filter), gate 1 (orthogonality), gate 2 (substitution test), effective-N estimator, BH-FDR wiring
- [ ] `tests/unit/test_acausal_placebo_registration.py` — D-05's per-provider registration gate
- [ ] `tests/unit/test_volatility_pct_pilot.py` — D-06's pilot provider implementation
- No new framework/config install needed — pytest is already fully configured project-wide.

---

## Manual-Only Verifications

*None — all phase behaviors have automated verification. This is a backend contract/governance
phase with no UI, no manual QA surface.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
