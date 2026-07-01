---
phase: 142A
slug: ensemble-ic-measurement-planned
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-30
---

# Phase 142A — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing — tests/unit/, tests/integration/, tests/e2e/) |
| **Config file** | pyproject.toml / pytest.ini (existing) |
| **Quick run command** | `.venv/bin/pytest tests/unit/ -q` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ tests/integration/ -q` |
| **Estimated runtime** | ~30 seconds (unit only); ~120 seconds (full) |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/ -q`
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ tests/integration/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~30 seconds

---

## Per-Task Verification Map

> Populated by the planner when PLAN.md task IDs exist. Phase 142A has 2 waves / 2 plans; each EIC-01..05 requirement maps to at least one task. Gate-evaluation tasks (EIC-04) and diagnosis tasks (EIC-05) are script-output verifiable (exit code + markdown report assertions).

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 142A-01-01..NN | 01 | 1 | EIC-01 | — | N/A (no PII, no auth; batch read-only on alpha_events/forward_returns) | unit | `.venv/bin/pytest tests/unit/ -q` | ✅ infra | ⬜ pending |
| 142A-02-01..NN | 02 | 2 | EIC-02/03/04/05 | — | N/A | unit + script | `.venv/bin/pytest tests/unit/ -q` | ✅ infra | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_ensemble_ic_engine.py` — stubs for EIC-01 (IC math parity, regime stratification, BH-FDR)
- [ ] `tests/unit/test_ensemble_ic_gate.py` — stubs for EIC-04 gate fraction evaluation
- [ ] EIC-05 diagnosis script (`ops_ensemble_ic_diagnosis.py`) — verified by grep (4 root-cause labels present) + `test -x`, NOT unit-tested (script is a render-only report; no unit-test stub needed)

*Existing pytest infrastructure covers framework/config. Wave 0 adds phase-specific test files.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| EIC-04 gate pass/fail on real corpus | EIC-04 | Depends on Phase B corpus re-run (alpha_events/forward_returns currently 0 rows) | After Phase B completes: run gate script, verify fraction-of-cells output; confirm threshold read from APR not hard-coded |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
