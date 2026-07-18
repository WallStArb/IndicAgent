---
status: pending
priority: P3
filed: 2026-07-17
source: phase 161 execution, /simplify pass (reuse review) — flagged but out of scope for a cleanup pass
---

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
