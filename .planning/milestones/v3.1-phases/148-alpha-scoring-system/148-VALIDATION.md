---
phase: 148
slug: alpha-scoring-system-v2-x-decommission-planned
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-22
---

# Phase 148 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 |
| **Config file** | project-root `pyproject.toml`/`pytest.ini` — existing `tests/unit/` convention |
| **Quick run command** | `.venv/bin/pytest tests/unit/test_alpha_scorer.py tests/unit/test_ensemble_ic_gate.py -q` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -q` |
| **Estimated runtime** | ~120 seconds |

---

## Sampling Rate

- **After every task commit:** Run the relevant new test file, quick-run above.
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 120 seconds

Additionally: the actual OOS gate runs (SCORE-02/SCORE-03 executed for real against live
data, not unit-tested with fixtures) are themselves a Wave 2 deliverable per CONTEXT.md
D-04's "run at most once per milestone gate" rule — these are NOT re-runnable smoke tests
and must not be re-triggered speculatively during iteration.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 148-01-xx | 01 | 1 | SCORE-01 | — | `AlphaScorer` correctly buckets `alpha_frames` into (symbol, tf, regime, decile) cells and filters N < `min_strategy_n` | unit | `.venv/bin/pytest tests/unit/test_alpha_scorer.py -x` | ❌ W0 | ⬜ pending |
| 148-01-xx | 01 | 1 | SCORE-01 | — | `ic_alpha_score_corr` computed correctly (monotonicity diagnostic) | unit | `.venv/bin/pytest tests/unit/test_alpha_scorer.py -x -k corr` | ❌ W0 | ⬜ pending |
| 148-01-xx | 01 | 1 | SCORE-02 | T-148-01 | OOS Gate 1 script fails loud when `alpha.validation.oos_start` unset | unit | `.venv/bin/pytest tests/unit/test_oos_gate1_signal_eval.py -x -k oos_start` | ❌ W0 | ⬜ pending |
| 148-01-xx | 01 | 1 | SCORE-02 | — | OOS Gate 1 script uses `_fisher_z_ci` (not circular-block-bootstrap) methodology, matching `ensemble_ic_engine.py` | unit | `.venv/bin/pytest tests/unit/test_oos_gate1_signal_eval.py -x -k methodology` | ❌ W0 | ⬜ pending |
| 148-02-xx | 02 | 2 | SCORE-03 | — | Gate 2 script correctly cites champion 143.1-08 pooled numbers without recomputing from a different population | unit/manual | `.venv/bin/pytest tests/unit/test_score03_gate2_execution_eval.py -x` | ❌ W0 | ⬜ pending |
| 148-02-xx | 02 | 2 | SCORE-03 | — | Regime-stratified companion never lets a pooled FAIL stand alone without the per-cell breakdown in the same output/row | unit | `.venv/bin/pytest tests/unit/test_score03_gate2_execution_eval.py -x -k regime_stratified` | ❌ W0 | ⬜ pending |
| — | — | — | — | — | Existing `evaluate_frame_gate`/`frame_gate_passes`/`compute_walk_forward_stable` machinery this phase reuses | regression | `.venv/bin/pytest tests/unit/test_counterfactual_tracker.py tests/unit/test_ensemble_ic_gate.py tests/unit/test_ensemble_ic_wf_stability.py -q` | ✅ (already exist) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_alpha_scorer.py` — stubs for SCORE-01
- [ ] `tests/unit/test_oos_gate1_signal_eval.py` — stubs for SCORE-02
- [ ] `tests/unit/test_score03_gate2_execution_eval.py` — stubs for SCORE-03
- [ ] No framework install needed — pytest already configured and green project-wide

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Promotion decision record accurately reflects both gate verdicts, discloses D-06's known-in-advance numbers, and pairs pooled with regime-stratified breakdown per D-07 | SCORE-03 / SCORE-04 | Requires human judgment that prose faithfully represents statistical findings without post-hoc reframing — not mechanically checkable | Read the promotion decision record; confirm it cites `143.1-08-SHADOW-VALIDATION.md` §6/§7 verbatim numbers, states both Gate 1 and Gate 2 verdicts independently, and does not conflate signal vs execution failure modes |
| SCORE-02/03 gate runs executed exactly once per `OOS-EVAL-PROTOCOL.md`'s frozen cadence rule (D-04) | SCORE-02 / SCORE-03 | Cannot be enforced by a test — requires operator discipline during execution, checked via `gate_evaluations` row count/timestamps after the fact | After Wave 2 execution, confirm `SELECT COUNT(*) FROM gate_evaluations WHERE gate_id IN ('gate1_signal','gate2_execution')` returns exactly 1 row per gate for this milestone |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
