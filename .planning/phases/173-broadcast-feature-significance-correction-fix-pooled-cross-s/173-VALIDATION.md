---
phase: 173
slug: broadcast-feature-significance-correction-fix-pooled-cross-s
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-24
---

# Phase 173 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (project standard, `.venv/bin/pytest`) |
| **Config file** | none — existing project pytest config applies |
| **Quick run command** | `.venv/bin/pytest tests/unit/services/test_ic_engine_compute_split.py tests/unit/services/test_ic_engine_fingerprint.py -q` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -q` |
| **Estimated runtime** | ~5-15s quick, several minutes full suite |

---

## Sampling Rate

- **After every task commit:** Run the quick command above
- **After every plan wave:** Run the full suite command
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

Filled in by the planner per-task against `173-RESEARCH.md`'s concrete line-number findings
(`_compute_cross_sectional_tf`, `_compute_one_cross_sectional_cell`, `_subsample_and_rank`,
`Float32ChunkAccumulator`, `_compute_symbol_tf`'s bespoke `CONTEXT_FEATURES` block, the
`ic_cell_fingerprints` `pass_type` gate) — no fixed table here since task breakdown isn't decided
yet at validation-strategy time.

---

## Wave 0 Requirements

- [ ] Live cross-check of the confirmed-broadcast feature population against `concept_registry`
      (research's Open Question 2 — D-02's "23" vs. the literal enumerated name-list count
      discrepancy) MUST resolve before any task that hardcodes the feature list.
- [ ] Decide the `ic_cell_fingerprints` `pass_type` for the new broadcast cell (research's Open
      Question 1) before the cell's fingerprint-gated call site is wired into `main()`.
- [ ] Decide the BH-FDR `cluster_id` scheme for broadcast rows (research's Open Question 3,
      recommends reusing `_cluster_features`) before any row is written to `feature_ic_scores`.

*Existing test infrastructure (`test_ic_engine_compute_split.py`, `test_ic_engine_fingerprint.py`)
covers the surrounding machinery this phase touches — no new test framework needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|--------------------|
| No OOM regression on `_compute_cross_sectional_tf` under the new `bar_ts`-threading change | D-05 | This function has a documented 2026-07-08 OOM incident (float32 conversion exists because of it); a unit test can't reproduce full-corpus memory pressure | Run the largest known cell (equity/5m, ~539K regime timestamps per this session's live observation) against the corpus and monitor RSS, not just correctness |
| Broadcast cell rows produce real, non-degenerate CIs (not the todo-204 stale-vintage `[0,0]` signature) on a fresh corpus pass | — | Requires a live `ic_engine` run against real data, not mockable | Run `ops_canary_integrity_assert.py` (or equivalent) against a fresh `feature_ic_scores` vintage populated by the new broadcast cell |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
