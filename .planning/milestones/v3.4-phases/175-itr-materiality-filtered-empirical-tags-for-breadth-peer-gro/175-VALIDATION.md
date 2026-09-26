---
phase: 175
slug: itr-materiality-filtered-empirical-tags-for-breadth-peer-gro
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-18
---

# Phase 175 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 (confirmed via `pytest.ini`) |
| **Config file** | `pytest.ini` (project root) |
| **Quick run command** | `.venv/bin/pytest tests/unit/test_tag_calibrator.py -x -q` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -q` |
| **Estimated runtime** | ~unknown — full suite, standard project convention |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/test_tag_calibrator.py -x -q`
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green. Additionally, the shadow-mode
  diagnostic's actual output (run against live/corpus data, not just unit-tested) must be
  reviewed by the user + cross-AI (D-03, D-07) before this phase is considered complete —
  this is a human/cross-AI review gate, not an automatable test.
- **Max feedback latency:** 120 seconds (quick command)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD-01 | TBD | 0 | P175-01 | — | Pass 4 computes a partial loading for a known synthetic (candidate, controls) pair matching a hand-derivable value | unit | `.venv/bin/pytest tests/unit/test_tag_calibrator.py::test_partial_loading_known_value -x` | ❌ W0 (new test, pattern matches existing `test_compute_factor_correlations_known_correlation_value`) | ⬜ pending |
| TBD-02 | TBD | 0 | P175-01 | — | Self-regression / degenerate-control guards (reuse `check_condition_number`) return NaN, never crash | unit | `.venv/bin/pytest tests/unit/test_tag_calibrator.py::test_pass4_ill_conditioned_controls_returns_nan -x` | ❌ W0 | ⬜ pending |
| TBD-03 | TBD | 0 | P175-02 | — | Migration adds new columns idempotently (`ADD COLUMN IF NOT EXISTS`), safe to re-run | integration (requires_db) | Manual `psql -f production/migrations/<N>_....sql` re-run twice, assert no error | N/A — no existing migration test harness in this codebase | ⬜ pending |
| TBD-04 | TBD | 0 | P175-04 | — | New APR keys resolve via `ConfigService.get_sync`/`get` at their seeded `[initial_estimate]` defaults | unit | `.venv/bin/pytest tests/unit/test_config_service.py -k materiality -x` (or extend existing `TagCalibratorConfig.from_apr` coverage) | ❌ W0 | ⬜ pending |
| TBD-05 | TBD | 0 | P175-05 | — | Circular-shift null-arm p-value computed correctly on a known synthetic series | unit | `.venv/bin/pytest tests/unit/test_tag_calibrator.py::test_null_arm_p_value -x` (or new `tests/unit/test_itr_materiality_shadow_diagnostic.py` per Open Question 2) | ❌ W0 | ⬜ pending |
| TBD-06 | TBD | 0 | P175-06 | — | A freshly-discovered empirical row is NOT `passes_materiality`-eligible until `discovery_oos_days` elapsed, independent of its statistical gate passing | unit | `.venv/bin/pytest tests/unit/test_tag_calibrator.py::test_discovery_oos_gate_blocks_fresh_discovery -x` | ❌ W0 — closes todo 125's originally-flagged gap | ⬜ pending |
| TBD-07 | TBD | 0 | P175-07 | — | Shadow diagnostic excludes `valid_to IS NOT NULL` rows from its membership delta | unit/integration | New test against `instrument_tags_active` view or diagnostic's query-building function | ❌ W0 | ⬜ pending |
| TBD-08 | TBD | 0 | P175-03 | — | Shadow diagnostic is read-only — no `INSERT`/`UPDATE`/`DELETE` against `market_regimes` or any consumer table | integration / static check | `grep -n "INSERT\|UPDATE\|DELETE" scripts/analysis/itr_materiality_shadow_diagnostic.py` asserting zero matches outside a comment | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky. Task IDs are placeholders — the planner assigns real plan/task IDs; this map is a requirement→test contract, not a literal task list.*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_tag_calibrator.py` — extend with Pass 4 unit tests (partial loading, ill-conditioning guard, discovery-OOS gate enforcement). File exists, needs new test functions, not a new file.
- [ ] `tests/unit/test_itr_materiality_shadow_diagnostic.py` — new file if the diagnostic script's logic (membership delta, null-arm) is substantial enough to warrant its own pure-function unit tests separate from `test_tag_calibrator.py` (recommended, matches this project's one-test-file-per-production-module convention).
- [ ] No dedicated migration-test harness exists in this codebase for any prior migration (230, 342, 343 all reviewed — none have an accompanying automated test). This phase should not invent one; manual idempotency verification (re-run twice) matches existing project practice.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Shadow-mode diagnostic's actual measured output (what would change if the filter went live) | D-02 (shadow-mode non-negotiable) | Requires human + cross-AI judgment on whether the measured materiality signal is real, not just that the code runs | Run the shadow diagnostic against corpus data, present the membership-delta output for review (D-03, D-07) before any consumer query changes |
| Migration idempotency re-run | P175-02 | No automated migration test harness exists project-wide (established practice, not a gap to fix in this phase) | `psql -f production/migrations/<N>_....sql` twice, confirm no error on second run |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
