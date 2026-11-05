---
status: pending
priority: P1
filed: 2026-11-04
source: lead (indicagent-4d), from the 575 landing handoff (indicagent-cb)
---

# One orchestrator for the corpus rerun and the fresh IC measure, tied to one run id

## What

`scripts/ops/ops_corpus_pipeline_run.sh` is dead since migration 570 (its regime_writer steps
refuse against the kernel table). The canary gate (`ops_canary_integrity_assert.py`) reads each
(tf, horizon) cell's latest vintage, not one ic_measure run, so a partial rerun is judged against
older cells. That gives a silently mixed verdict.

## Decision (lead, 2026-11-04)

One plan covers the 584 corpus rerun (pilot G1-G5, then 1d, then intraday, on the full universe so
stage-end compression runs), the fresh `ic_measure` run (186-28) and the canary gate. Every gate
reads the rows of one run id: the provenance_batch rows of the rerun and the ic_measure run's own
records. Replace the shell orchestrator, and don't patch it. Its steps are a DAG of oneshots with
explicit preconditions; each refuses loudly on a missing upstream run.

Planned now; it runs only when the 584 data gate passes (534 complete, owner rule 2026-11-04).
`LOOKAHEAD_FALLBACKS_BY_TF` in `services/_batch_utils.py` is retired with todo 554, not here.

## Done when

The plan is in `.planning/phases/` (or a 186 plan), reviewed. The canary gate takes a run id and
refuses cells from any other run (with a test). The dead shell orchestrator is deleted.

## Plans written (2026-11-05, indicagent-cb; released to the lead for a fresh session)

- `186-30-PLAN.md` (wave 10, migration 578): run identity (corpus_run with immutable identity,
  append-only caveats, spans and free_bytes_at_launch; corpus_run_step; provenance_batch.run_id
  outside batch_key and unit_key, movable only on a takeover to started), the rebuild's Jan-1
  intraday `span` and `chunk_indices` (execution filters only; every unit's completion comes from
  its own provenance row), ic_measure --run-id, and the canary gate judging one run over the APR
  tf list.
- `186-32-PLAN.md` (wave 10, migration 579): the APR seeds for the rerun and the continuity data
  gate (every exchange-calendar session per name-year, 1d and 5m, policy-resolved vendor pairs,
  names without a start or sessions refused unless held by a recorded rule) with the pre-2016
  survivorship caveat (todo 534 owner decision 2026-11-04).
- `186-31-PLAN.md` (wave 11, after 186-30 and 186-32): the step runner `services/corpus_rerun.py`,
  span-major (1d whole history first, then per span 1h, 15m, 5m); span count from
  infra.corpus_rerun.max_disk_fraction of free space at launch (about five or six spans at the 534
  target), a per-unit disk guard before each COPY, a pilot of chunk 0 of stage_1d plus one 1h unit
  that re-projects the spans, a detached worktree pin, recovery, and the deletion of the dead
  orchestrator.
- Plan check: five rounds with gsd-plan-checker; round five's items (data_gate silent passes, the
  186-32 split, policy-read eras, one-transaction caveat, timer service check, pilot intraday
  measurement, 1d calendar continuity) are applied. Next: execute 186-30 and 186-32 (parallel),
  then 186-31, each through /simplify, /review and tools/gate.py.

