---
**Created:** 2026-07-05
**Area:** intelligence
**Type:** architecture
**Priority:** P3
**Effort:** 0.5-1 day
**Benefit:** Restores DAG Invariant 2/3 discipline (compute never owns schema mutation); removes a startup race/failure mode from the hot pipeline
**Risk:** low
---

# 061 — Move `ensure_instruments_trigger()` DDL out of FeatureVectorPipeline hot path

Surfaced during the 2026-07-05 CLAUDE.md audit (Fable review). `FeatureVectorPipeline._setup()`
(`services/feature_vector_pipeline.py`) holds its own `DatabaseManager` and calls
`self._db.ensure_instruments_trigger()` — a DDL operation (`CREATE TRIGGER`/`CREATE FUNCTION`
class of statement) — directly inside the live compute daemon's startup path.

Per the "compute ≠ persistence ≠ transport" SoC principle and DAG Invariants 2/3 (reworded in
this same audit pass to precisely state: compute daemons may read/bootstrap-config for
themselves, but must never own schema mutation or persist their own computed output), this is
a real code smell, not just a documentation gap:

- DDL running inside a hot daemon's startup is a side effect outside the DAG's one-way data
  flow — it couples pipeline liveness to schema state in a way that's invisible to anyone
  reading the DAG topology.
- If multiple `FeatureVectorPipeline` instances ever start concurrently (blue/green deploy,
  crash-restart race), concurrent `CREATE TRIGGER` DDL is a plausible source of a startup race
  that wouldn't show up in normal single-instance operation.
- The trigger this sets up (instrument change notifications for `CacheManager`) is schema
  bootstrap, conceptually a migration concern, not a per-process runtime concern.

**Fix:** move `ensure_instruments_trigger()` into a migration (idempotent `CREATE OR REPLACE`/
`IF NOT EXISTS` already, so this is a relocation, not new logic) or a one-time bootstrap script
run outside the daemon's `_setup()`. `FeatureVectorPipeline` should assume the trigger already
exists and fail loudly (not silently degrade) if `CacheManager`'s instruments-listener can't
attach — per "silent wrong answers are worse than loud crashes."

**Gate:** none — can be done standalone whenever convenient, no dependency on other in-flight
phases.
