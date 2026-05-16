---
phase: 82
slug: ml-intelligence-quality-qualitative-foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-13
---

# Phase 82 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | `pytest.ini` / `pyproject.toml` |
| **Quick run command** | `.venv/bin/pytest tests/unit/ -v -x` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -v` |
| **Estimated runtime** | ~60 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/ -v -x`
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 82-01-01 | 01 | 1 | P82-DATA02 | — | N/A | manual | `python production/scripts/validate_alpha.py --plugin DerivativeOscillatorPlugin` | ✅ | ⬜ pending |
| 82-02-01 | 02 | 2 | P82-HMM-MULTITF | — | Per-TF lookback isolation | unit | `.venv/bin/pytest tests/unit/ -k hmm -v` | ❌ W0 | ⬜ pending |
| 82-03-01 | 03 | 3 | P82-HMM-MULTITF | — | Training writes params only | unit | `.venv/bin/pytest tests/unit/ -k hmm_train -v` | ❌ W0 | ⬜ pending |
| 82-04-01 | 04 | 2 | P82-REGIME-TRANSITION | — | Soft multiplier 0.0–1.0 in prob band | unit | `.venv/bin/pytest tests/unit/ -k regime_gate -v` | ❌ W0 | ⬜ pending |
| 82-05-01 | 05 | 4 | P82-FEATURE-VALIDATION | — | IC/p-value computed and stored | unit | `.venv/bin/pytest tests/unit/ -k feature_validation -v` | ❌ W0 | ⬜ pending |
| 82-06-01 | 06 | 4 | P82-CTX-SCHEMA | — | ctx persisted to DB, NULL on missing | unit | `.venv/bin/pytest tests/unit/ -k ctx_writer -v` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_hmm_regime_multitf.py` — stubs for P82-HMM-MULTITF
- [ ] `tests/unit/test_hmm_training_agent.py` — stubs for HMMTrainingAgent
- [ ] `tests/unit/test_regime_gate_soft.py` — stubs for P82-REGIME-TRANSITION
- [ ] `tests/unit/test_feature_validation_agent.py` — stubs for P82-FEATURE-VALIDATION
- [ ] `tests/unit/test_ctx_writer_agent.py` — stubs for P82-CTX-SCHEMA

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| DerivOsc/ACOsc actual promotion/demotion | P82-DATA02 | Requires live prod DB with resolved outcomes | Run `validate_alpha.py --plugin DerivativeOscillatorPlugin` and `--plugin ACOscillatorPlugin`; check output |
| HMM per-TF params hot-reload via SIGUSR1 | P82-HMM-MULTITF | Requires live service and signal | `kill -SIGUSR1 $(pgrep -f intelligence_pipeline)` then check logs |
| ctx JSONB populated on bar insert | P82-CTX-SCHEMA | Requires live bar pipeline | Insert a ctx_snapshot then observe next bar in `intelligence_features.ctx` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
