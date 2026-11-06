---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: 31
subsystem: corpus-rerun-step-runner
tags: [corpus-rerun, run-id, disk-budget, dag, canary, todo-593, todo-584]
requires: [186-30, 186-32]
provides: [services/corpus_rerun.py step runner, services/corpus_rerun_budget.py span planner and UnitDiskGuard, adoption list (belongs_to_run), docs/operations/corpus-rerun-runbook.md]
affects: [184, 186-28]
tech-stack:
  added: []
  patterns: [step DAG with upstream refusal and stored outcomes, injectable effects for the runner, pure disk projection over month counts, adoption of identical completed units]
key-files:
  created: [services/corpus_rerun.py, services/corpus_rerun_budget.py, tests/unit/services/test_corpus_rerun.py, tests/unit/services/test_corpus_rerun_budget.py, tests/integration/test_corpus_rerun_store.py, docs/operations/corpus-rerun-runbook.md]
  modified: [services/backfill_feature_factory.py, services/rebuild_preconditions.py, services/_batch_utils.py, scripts/ops/alpha/ops_canary_integrity_assert.py, services/ic_measure.py]
  deleted: [scripts/ops/corpus/ops_corpus_pipeline_run.sh, scripts/ops/corpus/ops_pipeline_monitor.sh, scripts/ops/corpus/ops_corpus_final_verification.py, src/observability/corpus_manifest_verifier.py, tests/unit/src/observability/test_corpus_manifest_verifier.py]
decisions:
  - "Adopted units live in the completed step's summary (corpus_run_step), no new table or migration; belongs_to_run in _batch_utils is the one rule the runner and the canary share"
  - "Row counts are per (tf, symbol chunk, month), pro-rated by day at a bound, so the straddling chunk and the largest group spool are measured, not guessed; they are stored in corpus_run.measured at --new-run"
  - "The APR hash (rerun APR plus the rebuild feature config) is pinned with the code key; pin_gate refuses a changed one"
  - "Pin checks repeat before every compute step; an unknown systemctl answer refuses"
requirements-completed: [D-19, D-32a, D-35]
metrics:
  completed: 2026-11-05
  tasks: 3
---

# Phase 186 Plan 31: the corpus rerun step runner Summary

`services/corpus_rerun.py` drives the 584 corpus rerun, the fresh ic_measure and the canary as one
DAG of oneshot steps under one `corpus_run` id, with a span count chosen from the disk limit, a
per-unit disk guard before every COPY, and the survivorship caveat written atomically with the
data gate result. No compute was launched; the only live invocation was the read-only
`--plan-only`.

## Commits

- 8d1b35c52 feat(186-31): disk budget, span planner and the per-unit disk guard
- 99df8d04e feat(186-31): the span-major corpus rerun step runner
- 93496fcec chore(186-31): delete the dead shell orchestrator and its verifier; corpus rerun runbook; close 593
- dba33887d refactor(186-31): one APR JSON reader; the identity probe closes its connection

## What landed

- `services/corpus_rerun_budget.py` (pure): `span_peak` with every term of the plan (span rows,
  straddling chunk, compressed rest, 1d uncompressed and compressed, max_wal_size, largest group
  spool), `daily_peak` for stage_1d, `plan_spans` (smallest fitting n, refuses with the candidate
  table), `project`/`overflowing` for the pilot's re-projection, `UnitDiskGuard`.
- `run_rebuild_stage(..., disk_guard)`: `_write_group` checks the guard on the unit's spool bytes
  before `_bulk_load`; a refusal counts the unit failed (reason disk_guard, with the numbers),
  writes no provenance row, stops dispatching, abandons the in-flight group and still compresses.
  Each load records the table's size delta per row and per spool byte (`bytes_per_row_max`,
  `stored_per_spool_max`); the guard tightens to the largest ratio. The summary lists the scope's
  batch keys and the units adopted from another run. Without a guard a stage builds one from free
  space at its start and the same APR keys.
- `check_disk_guard(projected_compressed_bytes, span_peak_bytes, wal_bytes, ...)`; `regime_writer`
  left `LIVE_RUN_PROCESS_PATTERN`.
- The runner: the steps of the plan, upstream refusal before any write, completed steps as
  no-ops, no skip flag, `--new-run [--plan-only]`, `--run-id X --step S | --through S`, one
  runner per run (advisory lock), logs and spool under the main checkout's `logs/`.
- Adoption (lead amendment): `RUN_ADOPTIONS_SQL` and `belongs_to_run` in `_batch_utils`; span
  steps, `feature_complete` and the canary count a unit only when its completed row is the run's
  or adopted with the same batch_key from the run it records.
- Runbook `docs/operations/corpus-rerun-runbook.md`; todo 593 closed.

## Plan-only run (live, read-only, 2026-11-05, horizon 2026-11-01)

Rows: 1d 6,963,199; 1h 33,786,859; 15m 123,138,219; 5m 354,505,514. Free 787 GB, limit 551 GB,
max_wal_size 17 GB, chunk interval 360 days. Two spans, [2006, 2020) and [2020, 2027).

| step | intraday | straddle | compressed | 1d unc | 1d cmp | wal | spool | peak (GB) |
|---|---|---|---|---|---|---|---|---|
| stage_1d | 0 | 0 | 0 | 9.6 | 0 | 17.2 | 0.5 | 27.3 |
| s1 | 350.9 | 0 | 0 | 8.4 | 0.2 | 17.2 | 20.0 | 396.7 |
| s2 | 354.3 | 33.5 | 52.9 | 3.7 | 1.0 | 17.2 | 12.1 | 474.6 |

Data gate: FAIL; 1,502 names, 13,894 failing name-years, 10 without a proven start; IBKR era
1,135 names (80 at depth, 489 partial, 566 none); Alpaca era 1,492 (849 / 640 / 3). The counts
grow with the 534 backfill (about 1.9x pre-2016 intraday), so the real run plans more spans.

## Verification

- Unit: test_corpus_rerun (43), test_corpus_rerun_budget (14), test_backfill_feature_factory
  (5 new guard, measurement and adoption tests), test_canary_predictors (3 new adoption tests),
  test_rebuild_preconditions (span term by name, regime_writer gone). Full suite via
  `tools/gate.py`: 8,044 tests, 0 failed, 8 skipped. repro_frozen not owed.
- Integration on indicagent_test: test_corpus_rerun_store (6): the data gate's result, caveat and
  completion in one transaction; a failure injected after the caveat append leaves none; a retry
  keeps one caveat; adoptions only from completed steps; the run lock is exclusive.

## Deviations from Plan

1. Step order follows the plan (data_gate -> pin_gate); the lead's brief listed pin_gate first.
   The pin checks also repeat before every compute step, so nothing runs unpinned either way.
2. [Rule 2] The APR hash joins the pin checks: corpus_run pins it, and a changed APR would
   otherwise move unit identities or the disk limits silently mid-run.
3. [Rule 2] An unknown `systemctl` answer for a blocking timer refuses (a typo'd unit name in
   the APR list would otherwise pass as "not enabled").
4. Row counts are per month, not per calendar year, so the straddling chunk (360-day chunks are
   not year aligned) and the largest per-chunk group spool are computed from counts. They are
   stored in `corpus_run.measured.row_counts` at --new-run, so every projection of the run reads
   the same inputs.
5. The pilot's 1h unit is the first year of span 1 in which symbol chunk 0 has one (the plan
   says the first year; chunk 0's names may start later). Still a Jan-1 sub-span of span 1.
6. The pilot runs G4-G5 on every chunk-0 name at 1d and 1h; `ops_pilot_compute_gate.py` computes
   to `default_data_horizon()`, not the run's horizon. G4/G5 judge causality and determinism, not
   stored values, so this does not weaken them; noted for 584.
7. `stage_1d` gets the same completeness test as the span steps.
8. `corpus_manifest_verifier` went entirely (feature_complete calls none of it). ic_measure still
   writes `.planning/corpus_manifests/ic_measure.json`, which now has no reader: deferred.
9. Protected docs keep their references to the deleted scripts as history:
   `docs/plans/2026-09-26-unified-research-to-production-design.md` (canonical),
   `methodology-change-ledger.md` (append only), `OOS-EVAL-PROTOCOL.md`, migration 430's comment,
   `.planning/phases|milestones|todos/completed` and `docs/research` records.
10. Reviews: Codex is out of quota and no subagent tool was available in this session, so the
    /simplify and /review passes were mine. They produced the refactor commit; the remaining
    review findings are the deferred items below.

## Deferred

- ic_measure's corpus manifest has no reader since the verifier's deletion (delete it or give it
  a reader).
- The pilot compute gate should take the run's horizon (`--horizon`) so G4-G5 read exactly the
  run's bars.

## Self-Check: PASSED

Files created exist; commits 8d1b35c52, 99df8d04e, 93496fcec and dba33887d are on the branch.
