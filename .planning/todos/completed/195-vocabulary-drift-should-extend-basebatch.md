---
status: completed
priority: P3
filed: 2026-07-17
closed: 2026-07-19
source: phase 161 execution, /simplify pass (reuse review) — flagged but out of scope for a cleanup pass
---

## Resolution

Converted the hand-rolled `main()`/`_run()` D-06 lifecycle to `VocabularyDriftAuditor(BaseBatch)`,
following `tag_calibrator.py`'s pattern (no manifest, plain `execute(pool)`). Report printing and
the `integrity_monitor`/OTel-counter side effects are unchanged; the main behavior difference is
that a genuine runtime error now propagates as an uncaught exception (BaseBatch's `run()`
re-raises after recording the D-06 failure metric) instead of a caught `return 1` -- matches
every other batch oneshot's convention. No behavior change for the caller:
`ops_corpus_pipeline_run.sh` already wraps the invocation in `|| true`, so a clean `return 1`
and a crash-induced nonzero exit were already indistinguishable to it. Also picked up file
logging (`logs/vocabulary_drift_audit.log`) for free via `BaseBatch.__init__`, which the old
hand-rolled version never had.

# `vocabulary_drift.py`'s oneshot entrypoint should extend `BaseBatch`

## Finding

`src/config/vocabulary_drift.py`'s `main()`/`_run()` hand-rolls the D-06 oneshot lifecycle
(try/except/finally, manual `JOB_COMPLETED_TOTAL.add(...)`, manual
`flush_and_shutdown_metrics()`) instead of extending `src/core/agent/base_batch.py`'s
`BaseBatch`, which every other batch oneshot in the codebase (`ic_engine`, `regime_writer`,
`forward_return_writer`, `backfill_feature_factory`, `ops_roll_batch.py`) either extends or
predates as a legacy script.

Not fixed inline during 161's `/simplify` pass — converting to `BaseBatch` is a real refactor
(CLI arg handling, lifecycle hooks, tests) with behavior-change risk, out of scope for a
same-session cleanup gate. The pool-creation half of this finding (raw `asyncpg.create_pool`
skipping JSONB codec registration) WAS fixed inline — see commit `e00b19ed`.

## Fix

Convert `vocabulary_drift.py`'s entrypoint to subclass `BaseBatch`, following the pattern in
one of the existing oneshots (`regime_writer.py` is probably the closest analog in size/shape).
Low urgency — current hand-rolled version works correctly, this is a consistency/maintainability
improvement, not a bug.
