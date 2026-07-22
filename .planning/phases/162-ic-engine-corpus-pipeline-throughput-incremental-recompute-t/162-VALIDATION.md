---
phase: 162
slug: ic-engine-corpus-pipeline-throughput-incremental-recompute-t
status: ready
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-22
---

# Phase 162 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 6.0+ (`pytest.ini`, `testpaths = tests`, `python_files = test_*.py`) |
| **Config file** | `pytest.ini` (repo root) |
| **Quick run command** | `.venv/bin/pytest tests/unit/test_ic_engine_compute_split.py tests/unit/test_ic_engine_idempotency.py tests/unit/test_ic_engine_incremental_write.py -q` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -q` |
| **Estimated runtime** | ~90 seconds (full suite, per this session's own runs earlier) |

---

## Sampling Rate

- **After every task commit:** Run the quick run command above (targeted files, <30s)
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -q` (full suite)
- **Before `/gsd:verify-work`:** Full suite must be green. 162-04's equivalence harness (fresh
  compute vs. fingerprint-skip on a ~5-symbol real-DB subset) runs separately as an ops script
  before the phase is declared done — it cannot run inside the unit-test sandbox.
- **Max feedback latency:** 30 seconds (quick run)

---

## Per-Task Verification Map

No locked requirement IDs exist for this phase (predates formal `REQUIREMENTS.md` IDs — this
project has no `.planning/REQUIREMENTS.md` file at all). Mapping is against the phase
description's own success criteria and RESEARCH.md's confirmed file list instead of REQ-IDs.

| Task ID | Plan | Wave | Criterion | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-----------|-----------|-------------------|-------------|--------|
| 162-01-xx | 01 | 1 | Structural equivalence: extracted `_compute_cross_sectional_tf` block bit-identical pre/post | unit (regression fixture, extends `be74f4a1`'s methodology) | `pytest tests/unit/test_ic_engine_compute_split.py -x` | Partial — extend | ⬜ pending |
| 162-01-xx | 01 | 1 | Todo 139/140 feature-blocked rank/CI bit-identical to unblocked | unit | `pytest tests/unit/test_ic_engine_compute_split.py::test_cross_sectional_rankdata_output_is_float32_not_float64 -x` (extend) | Partial | ⬜ pending |
| 162-01-xx | 01 | 1 | `build_walk_forward_folds` matches all 4 existing inline call sites | unit (NEW) | `pytest tests/unit/test_ic_math_walk_forward_folds.py -x` | Wave 0 gap | ⬜ pending |
| 162-01-xx | 01 | 1 | `short_lived_conn(dsn)`: 3 call sites migrated; exception mid-fetch still closes conn | unit (NEW) | `pytest tests/unit/test_batch_utils_short_lived_conn.py -x` | Wave 0 gap | ⬜ pending |
| 162-02-xx | 02 | 2 | Per-tf bootstrap thread dict assembled from 4 flat APR keys | unit | extend `tests/unit/test_ic_engine_parallelism.py` | Partial | ⬜ pending |
| 162-03-xx | 03 | 3 | Fingerprint skip/invalidate: match skips, mismatch DELETEs+recomputes, unclassified field crashes loud | unit (NEW) | `pytest tests/unit/test_ic_engine_fingerprint.py -x` | Wave 0 gap | ⬜ pending |
| 162-03-xx | 03 | 3 | Idempotency preserved: existing `DO NOTHING` assertions unchanged | unit (existing, must NOT need editing per Pitfall 1's design) | `pytest tests/unit/test_ic_engine_idempotency.py -x` | Exists | ⬜ pending |
| 162-03-xx | 03 | 3 | BH-FDR family coherence: `_backfill_bh_fdr` still scoped to full `training_window_end` | unit (existing) | `pytest tests/unit/test_ic_engine_incremental_write.py -x` | Exists | ⬜ pending |
| 162-04-xx | 04 | 4 | Equivalence harness: fresh vs. fingerprint-skip identical `feature_ic_scores` on ~5 symbols | integration (NEW, DB-backed, ops script) | manual/ops script — not a `pytest tests/unit/` case | Wave 0 gap | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

**Satisfied via inline TDD authorship, not a separate upfront wave** — each new test file below
is written within the same task that implements the behavior it covers (confirmed by
`gsd-plan-checker`'s Dimension 8d review as a valid TDD shape, not a broken Wave-0 link):

- [x] `tests/unit/test_ic_math_walk_forward_folds.py` — authored in 162-01 Task 2, covers
      `build_walk_forward_folds` against all 4 existing inline call sites' expected boundary values
- [x] `tests/unit/test_batch_utils_short_lived_conn.py` — authored in 162-01 Task 1, covers the
      new dsn-based `short_lived_conn` context manager, including the
      exception-mid-fetch-still-closes case the 3 existing hand-rolled sites fail today
- [x] `tests/unit/test_ic_engine_fingerprint.py` — authored in 162-03 Tasks 1-3, covers the
      fingerprint validity check (match/mismatch/unclassified-field-crashes-loud), the
      in-place-mutation watermark test, the DELETE-then-insert invalidation path, and that
      `existing_keys`'s replacement still integrates correctly with `worker_args` construction
- [x] Framework install: none — pytest and all dependencies already present

---

## Manual-Only Verifications

| Behavior | Criterion | Why Manual | Test Instructions |
|----------|-----------|------------|--------------------|
| 162-04 equivalence harness | Fresh-compute vs. fingerprint-skip runs produce identical `feature_ic_scores` on a real ~5-symbol subset | Requires a live DB with real corpus data and two full `ic_engine` invocations — not something the unit-test sandbox can exercise | Run `ic_engine.py` twice against the same ~5-symbol/tf subset (once `--refresh`, once fingerprint-skip path), diff `feature_ic_scores` rows for byte/value equality including `bh_adjusted_p`/`passes_fdr` |
| No-op re-run wall-clock (success criterion 1) | Full 80-symbol re-run with unchanged inputs completes in <30min vs. 25-30h today | Requires a full corpus run, not a unit test | Time a full `ic_engine.py` invocation with zero invalidated cells after 162-03/04 land |
| Synthetic oversized-cell memory test (success criterion 6) | A cell ~2x today's largest completes within a measured resident-memory budget | Requires deliberately allocating multi-GB and measuring peak RSS — not a normal unit test, and must not run while a real `ic_engine` corpus run is in flight (resource contention) | Run the synthetic oversized-cell script from 162-01's closing gate with `ps aux | grep ic_engine` confirmed clear first |

---

## Validation Sign-Off

Verified by `gsd-plan-checker` against the 4 committed plans (2026-07-22), 0 blockers:

- [x] All tasks have automated verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all Wave-0-gap rows above (3 new test files, authored inline per task)
- [x] No watch-mode flags
- [x] Feedback latency < 30s (quick run)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-07-22 (gsd-plan-checker, VERIFICATION PASSED — 0 blockers, 2
warnings, both bookkeeping-only and since fixed in this file and 162-RESEARCH.md)
