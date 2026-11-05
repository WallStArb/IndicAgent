---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: 30
subsystem: corpus-rerun-run-identity
tags: [provenance, run-id, migration, rebuild-writer, ic-measure, canary-gate]
requires: [186-27]
provides: [corpus_run and corpus_run_step (migration 578), provenance_batch.run_id, run_rebuild_stage run_id/span/chunk_indices, ic_measure --run-id, canary gate --run-id]
affects: [186-31, 186-32]
tech-stack:
  added: []
  patterns: [run id as execution metadata outside the unit identity, filters on the execution list only, repeatable-read snapshot for check-then-read]
key-files:
  created: [production/migrations/578_corpus_run.sql]
  modified: [services/_batch_utils.py, services/backfill_feature_factory.py, services/ic_measure.py, scripts/ops/alpha/ops_canary_integrity_assert.py, tests/unit/test_bulk_load.py, tests/unit/services/test_backfill_feature_factory.py, tests/unit/test_ic_measure.py, tests/unit/test_canary_predictors.py, tests/unit/test_table_and_apr_key_readers.py, tests/integration/test_ic_measure.py]
decisions:
  - "provenance_batch.run_id is execution metadata outside batch_key and unit_key; it moves only on a takeover to started and is frozen on a completed row (578 guard)"
  - "corpus_run.caveats append only is enforced as a prefix check (every old element at its position), stricter than NEW @> OLD"
  - "The canary gate resolves each APR tf's proposer unit through ic_measure.job_writer/job_replace_where and bulk_load_unit_key, the same definitions the writer uses"
requirements-completed: [D-17, D-24, D-35]
metrics:
  completed: 2026-11-05
  tasks: 3
---

# Phase 186 Plan 30: run identity for the corpus rerun Summary

One run id now travels with every row the rebuild and ic_measure write, the rebuild can execute
the intraday history span by span (or one symbol chunk) without changing what it plans, and the
canary gate judges exactly one run. Migration 578 is applied live. No compute was launched.

## Commits

- 132255cc6 feat(186-30): corpus_run identity and provenance_batch.run_id (migration 578, applied live)
- 0fbe1ee3e feat(186-30): run_id and the intraday span in the rebuild writer; ic_measure --run-id
- a9b0789db feat(186-30): the canary gate judges one run
- 9cb7b9246 refactor(186-30): one comparison for the span's Jan 1 UTC bound check
- the docs commit carrying this summary, STATE, ROADMAP, PRIORITIES and todo 593

Review: two independent AGY rounds (the second quoting code and tests for each must_have and
hunting four named failure classes) found nothing material.

## What landed

- Migration 578: `corpus_run` (identity columns immutable by `fn_corpus_run_guard`, caveats append
  only, data_gate, measured, status), `corpus_run_step` (PK run_id, step), `provenance_batch.run_id`
  uuid NULL with index (run_id, status), and `fn_provenance_batch_guard` replaced: run_id changes
  only when NEW.status = started and OLD.status in (started, failed); run_id joins the
  completed-row frozen list.
- `BulkLoadSpec.run_id` (canonical uuid string or None, outside both keys); the provenance INSERT
  records it and the takeover UPDATE re-stamps it. `parse_run_id` is the argparse type of every
  --run-id. `bulk_load_unit_key` is the module-level definition `BulkLoadSpec.unit_key` calls.
- `run_rebuild_stage(..., run_id, span, chunk_indices)`: span bounds must be Jan 1 00:00 UTC and
  start < end; a stage holding 1d refuses a span; chunk indices outside the chunking are refused.
  The planning loop consults `_completed_provenance_batch` for every unit of every planned group
  before the span and chunk filters decide the execution list, so `planned` and the compression
  bound carry provenance-derived states for filtered-out units. Executed specs carry run_id. The
  summary adds `units_out_of_scope`; units_total, units_skipped and the chunk checklist count the
  executed scope.
- ic_measure: `TfRun.run_id` from `--run-id`, set on every spec; `job_writer` and
  `job_replace_where` are the one definition of a job's unit.
- Canary gate: required `--run-id`; tfs from APR `feature.factory.target_timeframes` (refused if
  missing or malformed); per tf, the proposer unit's provenance rows must hold exactly one
  completed row under the run, then its cells are read by the unit's scope, all inside one
  repeatable-read read-only transaction; every failing tf is named in one violation. The
  latest-vintage subquery is gone.

## Verification

- Live guard checks in a rolled-back transaction: (a) run_id change on started -> completed
  raises; (b) run_id change (to another id or NULL) on completed -> superseded raises; (c)
  corpus_run code_commit, code_key and spans updates raise; (d) caveats dropping, rewriting or
  reordering an element raises. Allowed: started -> started re-stamp, plain completion and
  supersede, an appended caveat with data_gate, measured and status updates. Nothing persisted.
- Unit: test_bulk_load (run_id class, 11 tests), test_backfill_feature_factory (13 new: span
  partition, refusals, three-span compression with the real `compression_bound`, the negative
  case, chunk_indices identities and known map), test_ic_measure (3 new), test_canary_predictors
  (14 new: other run, superseded, missing tf, no cells, APR tf list, CLI). Full suite through
  `tools/gate.py`: 7,916 collected, passed. repro_frozen not required (no research or statistics
  file changed).
- Integration: tests/integration/test_ic_measure.py (10, now under run ids: every completed row
  records run 1; a rerun under run 2 skips and writes no run 2 row), test_bulk_load.py (12),
  test_migration_schema_sync.py (1), all passing.
- Read-only smoke: the canary against the live database with an unknown run id exits 1 naming
  all four tfs as missing.

## Deviations from Plan

1. [Rule 2] Caveats append-only is a prefix check (each old element at its old position) rather
   than the plan's `NEW.caveats @> OLD.caveats`: jsonb containment passes an element rewritten by
   adding keys and a dropped duplicate. Stricter, same intent.
2. [Rule 3] `corpus_run_step` has no reader until 186-31, so the reader guard failed; it has a
   `_KEEP_TABLES` entry in tests/unit/test_table_and_apr_key_readers.py that 186-31 removes.
3. [Rule 3] tests/integration/test_ic_measure.py (not in the plan's file list) needed `run_id` in
   its argument namespace; cases 1 and 2 now also assert the recorded run ids.
4. [Rule 2] The canary also refuses a run whose unit holds no canary cell for a tf, and a unit
   with more than one completed row; a run id that is not a canonical uuid is refused at parse
   time (CLI) and by `BulkLoadSpec`.
5. `bulk_load_unit_key` and `ic_measure.job_writer`/`job_replace_where` were factored out so the
   canary recomputes the unit key from the writer's own definitions instead of a copy.

## Notes for 186-31

- A unit skipped because it is already completed keeps the run it was loaded under. If the IC
  inputs of a later run are bit-identical to an earlier run's, ic_measure skips and the canary
  refuses the later run (completed under another run). This is loud, by design of the plan; the
  runner should expect it on a re-invocation across run ids.
- The dead `scripts/ops/corpus/ops_corpus_pipeline_run.sh` calls the canary without --run-id; it
  is deleted by 186-31.

## Self-Check: PASSED

Files and commits verified present after writing (see the final docs commit).
