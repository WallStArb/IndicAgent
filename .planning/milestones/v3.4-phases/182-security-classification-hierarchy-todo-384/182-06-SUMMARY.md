---
phase: 182-security-classification-hierarchy-todo-384
plan: 06
subsystem: config / observability
tags: [classification, coverage-audit, integrity-monitor, nightly-chain, D-09, D-08]
requires: [182-01]
provides: [ClassificationCoverageAuditor, uncovered_symbols, unclassified_counts_by_level]
affects: [scripts/ops/corpus/ops_corpus_pipeline_run.sh, integrity_monitor]
tech-stack:
  added: []
  patterns: [BaseBatch oneshot observability audit (VocabularyDriftAuditor template)]
key-files:
  created:
    - src/config/classification_coverage.py
    - tests/unit/test_classification_coverage.py
  modified:
    - scripts/ops/corpus/ops_corpus_pipeline_run.sh
decisions:
  - Coverage is measured through ClassificationService (level-1 node as of today is unclassified means uncovered), not a second SQL definition of "covered"
  - Per-level stratum facts are informational (passed=true, threshold NULL); only uncovered_active_count can fail
  - With an empty registry max_level is 0, so no per-level facts are emitted; the uncovered count still reports every active instrument
metrics:
  duration: ~15 min
  completed: 2026-09-25
  tasks: 2
  files: 3
---

# Phase 182 Plan 06: Classification coverage drift audit summary

Nightly, non-gating `ClassificationCoverageAuditor` reports every active instrument without a current `indicagent_v1` assignment (integrity_monitor fact, OTel counter, `logger.error` with the symbols) and the unclassified stratum size per level, measured through `ClassificationService` as its first production consumer.

## Tasks

| Task | Name | Commits |
| ---- | ---- | ------- |
| 1 | ClassificationCoverageAuditor with pure coverage functions (TDD) | b270d06b6 (RED), 3322b72ec (GREEN) |
| 2 | Chain the audit into the nightly corpus pipeline | 136fdd623 |

## Verification

- `tests/unit/test_classification_coverage.py`: 8 passed, no DB.
- Live dry run before migration 365 (seed not applied): `python -m src.config.classification_coverage` exited 0 and printed `Uncovered active instruments: 273` (all 273 active instruments), proving the audit is loud on a real gap. `integrity_monitor` rows for `monitor_type='classification_coverage'` went from 0 to 1 (`uncovered_active_count=273, passed=false`). No per-level rows yet because the empty registry has max_level 0; Plan 07 should see levels 1-4 appear after the seed.
- `bash -n` on the pipeline script passes; the new step is backgrounded with `|| true`, sits after the vocabulary drift step, and is not wrapped in `run_step`.
- Full unit suite: the only failure is `tests/unit/research/test_portfolio_r1.py::test_rank_vol_neutral_returns_meets_performance_target`, the known load-sensitive timing test owned by the concurrent phase 183 session.

## Deviations from plan

None. Plan executed as written. The pre-commit hook re-sorted one import in the test file before the RED commit; no behavioral change.

## Known stubs

None.

## Self-Check: PASSED

- FOUND: src/config/classification_coverage.py
- FOUND: tests/unit/test_classification_coverage.py
- FOUND commits: b270d06b6, 3322b72ec, 136fdd623
