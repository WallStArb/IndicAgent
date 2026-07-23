---
phase: 166
slug: frame-execution-recalibration
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-23
---

# Phase 166 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 6.0+ (`pytest.ini`, `asyncio_mode = auto`) |
| **Config file** | `pytest.ini` (repo root) |
| **Quick run command** | `.venv/bin/pytest tests/unit/test_ensemble_ic_decay.py tests/unit/test_alpha_frame_writer_geometry.py tests/unit/test_counterfactual_tracker_exit_priority.py tests/unit/trading/test_zone_engine.py -q` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -q` |
| **Estimated runtime** | ~30-60 seconds (quick), several minutes (full suite) |

---

## Sampling Rate

- **After every task commit:** Run the quick run command above (targeted to the new test file(s) for that task's function(s))
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -q` (full suite)
- **Before `/gsd:verify-work`:** Full suite must be green; the new gate script's `--dry-run` output must be manually reviewed before its one real (OOS-touching) run per candidate (RESEARCH.md Pitfall 5 — no repeated OOS peeking)
- **Max feedback latency:** ~60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 166-XX-XX | TBD | 0 | D-01a (diagnosis vs IC decay curve) | — | N/A (read-only analysis) | integration | manual run of new diagnosis script against live DB | ❌ W0 | ⬜ pending |
| 166-XX-XX | TBD | 0 | D-01b (scalar candidate calibration, CR-02 gated) | — | N/A | unit | `pytest tests/unit/test_ensemble_ic_stop_target_calibration.py -x` | ❌ W0 | ⬜ pending |
| 166-XX-XX | TBD | 0 | D-01c (structural candidate Part 1, VP/SR confluence) | — | N/A | unit | `pytest tests/unit/test_structural_confluence.py -x` | ❌ W0 (also blocked on Phase 163 for live-data integration) | ⬜ pending |
| 166-XX-XX | TBD | 0 | D-01d (new validation gate, new gate_id) | — | N/A | unit + integration | `pytest tests/unit/test_gate166_frame_recalibration_eval.py -x` | ❌ W0 | ⬜ pending |
| 166-XX-XX | TBD | 0 | D-04 (new gate_id, not gate2_execution re-run) | — | N/A | unit + live DB check | `pytest -k test_gate166_uses_new_gate_id` + `SELECT DISTINCT gate_id FROM gate_evaluations` | ❌ W0 | ⬜ pending |
| 166-XX-XX | TBD | 0 | D-05 (regime-window coverage disclosed, not gated) | — | N/A | unit | mirrors `test_score03_gate2_execution_eval.py`'s regime-companion assertions | ❌ W0 (pattern exists to copy) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky. Task IDs finalized once the planner assigns them; requirement source is CONTEXT.md's D-01 through D-06 (no formal REQ-IDs exist yet for this phase).*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_ensemble_ic_stop_target_calibration.py` — covers D-01b, mirrors `tests/unit/test_ensemble_ic_decay.py`'s structure
- [ ] `tests/unit/test_structural_confluence.py` — covers D-01c, mirrors `tests/unit/trading/test_zone_engine.py`'s synthetic-candidate style
- [ ] `tests/unit/test_gate166_frame_recalibration_eval.py` — covers D-01d/D-04/D-05, mirrors `tests/unit/test_score03_gate2_execution_eval.py` almost exactly
- No new pytest fixtures or `conftest.py` changes anticipated — existing patterns (synthetic dict rows, no live DB needed for unit tests) fully cover this phase's testable surface

*(Framework install: none needed — pytest already configured project-wide.)*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|--------------------|
| New gate script's OOS `--dry-run` output | D-01d, D-03 | Automated tests use synthetic rows; the real evidentiary comparison of scalar vs. structural candidate against live OOS data requires human review before the one-shot real run (holdout discipline, Pitfall 5) | Run `scripts/analysis/gate166_frame_recalibration_eval.py --dry-run` for each candidate, review printed verdict + regime companion table, confirm no repeated re-runs before finalizing calibration |
| Phase 163 execution as Wave 0 prerequisite | D-06 | Cross-phase dependency, not a Phase 166 code change | `/gsd-execute-phase 163`, then `SELECT count(*) FROM feature_vectors WHERE sr_support_dist IS NOT NULL` returns >0 before starting the structural candidate's implementation wave |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
