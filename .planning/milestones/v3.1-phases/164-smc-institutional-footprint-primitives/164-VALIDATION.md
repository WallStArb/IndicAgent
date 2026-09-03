---
phase: 164
slug: smc-institutional-footprint-primitives
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-25
---

# Phase 164 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | pytest.ini / pyproject.toml |
| **Quick run command** | `.venv/bin/pytest tests/unit/intelligence/ -q` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -q` |
| **Estimated runtime** | intelligence-scoped: seconds; full suite (369 files): several minutes — full suite reserved for wave-exit/pre-verify-work only, never a per-task gate (see 164-04's Task 2 fix, checker warning W4) |

---

## Sampling Rate

- **After every task commit:** Run quick run command
- **After every plan wave:** Run full suite command
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 164-01-01 | 01 | 1 | REQ-164-09 | — | N/A | unit+db | `.venv/bin/pytest tests/unit/test_feature_vector_persistence_completeness.py -x -q` | ✅ | ⬜ pending |
| 164-01-02 | 01 | 1 | REQ-164-09 | — | N/A | db+ruff | `.venv/bin/ruff check src/intelligence/feature_factory.py services/feature_vector_pipeline.py services/backfill_feature_factory.py` | ✅ | ⬜ pending |
| 164-01-03 | 01 | 1 | REQ-164-09 | — | N/A | unit | `.venv/bin/ruff check src/intelligence/feature_cache.py` | ✅ | ⬜ pending |
| 164-02-01 | 02 | 2 | REQ-164-01, REQ-164-02 | — | N/A | unit (RED) | `.venv/bin/pytest tests/unit/intelligence/test_smc_order_blocks.py -x -q` (expected RED) | ✅ W0 | ⬜ pending |
| 164-02-02 | 02 | 2 | REQ-164-01, REQ-164-02 | — | N/A | unit (tdd) | `.venv/bin/pytest tests/unit/intelligence/test_smc_order_blocks.py tests/unit/intelligence/test_feature_factory_batch_parity.py -x -q` | ✅ | ⬜ pending |
| 164-03-01 | 03 | 3 | REQ-164-03, REQ-164-04, REQ-164-05 | — | N/A | unit (RED) | `.venv/bin/pytest tests/unit/intelligence/test_smc_fvg.py -x -q` (expected RED) | ✅ W0 | ⬜ pending |
| 164-03-02 | 03 | 3 | REQ-164-03, REQ-164-04, REQ-164-05 | — | N/A | unit (tdd) | `.venv/bin/pytest tests/unit/intelligence/test_smc_liquidity.py tests/unit/intelligence/test_smc_fvg.py tests/unit/intelligence/test_feature_factory_batch_parity.py -x -q` | ✅ | ⬜ pending |
| 164-04-01 | 04 | 4 | REQ-164-06, REQ-164-07 | — | N/A | unit (tdd) | `.venv/bin/pytest tests/unit/intelligence/test_smc_zones.py tests/unit/intelligence/test_smc_structure.py tests/unit/intelligence/test_feature_factory_batch_parity.py -x -q` | ✅ | ⬜ pending |
| 164-04-02 | 04 | 4 | REQ-164-08 | — | N/A | unit (tdd) + full suite (wave-exit) | `.venv/bin/pytest tests/unit/intelligence/test_smc_amd_cycle.py -x -q` then `.venv/bin/pytest tests/unit/intelligence/ -q` then `.venv/bin/pytest tests/unit/ -q` (wave-exit gate, not per-task latency budget) | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*
*Threat Ref / Secure Behavior columns are N/A — this phase has no auth/security-sensitive surface (internal batch/live feature compute only, confirmed by plan-checker Dimension 7c).*

---

## Wave 0 Requirements

- [x] `tests/unit/intelligence/test_smc_order_blocks.py` — RED-first stub, Plan 02 Task 1
- [x] `tests/unit/intelligence/test_smc_fvg.py` / `test_smc_liquidity.py` — RED-first stubs, Plan 03 Task 1
- [x] `tests/unit/intelligence/test_smc_zones.py` / `test_smc_structure.py` / `test_smc_amd_cycle.py` — RED-first fixtures, Plan 04 Tasks 1-2
- [x] `tests/unit/test_feature_vector_persistence_completeness.py` — existing completeness/drift-gate test, extended by Plan 01 Task 1 to cover the 36 new SMC fields, not newly created

Wave 0 (RED) tests are written as the first task of each compute plan (02/03/04), not as a separate
upfront wave — each plan's own Task 1 is the RED stub, per this project's standard TDD-plan shape.
`wave_0_complete` in frontmatter stays `false` until these RED tests actually land during execution
(this file records intent at plan time, not execution state).

---

## Manual-Only Verifications

*None identified — all phase behaviors (feature computation) have automated verification via unit tests against synthetic and historical bar fixtures.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (checker Dimension 8a: PASS, all 9 tasks checked)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (checker Dimension 8c: PASS)
- [x] Wave 0 covers all MISSING references (checker Dimension 8d: N/A, no MISSING placeholders used)
- [x] No watch-mode flags
- [x] Feedback latency < 120s (per-task scope; 164-04-02's full-suite line moved to wave-exit-only, checker W4 fix applied)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-07-25 (gsd-plan-checker VERIFICATION PASSED, 4 non-blocking warnings, all 4 applied)
