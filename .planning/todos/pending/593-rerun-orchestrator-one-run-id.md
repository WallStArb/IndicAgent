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

- `186-30-PLAN.md`: run identity (corpus_run, corpus_run_step, provenance_batch.run_id outside
  batch_key and unit_key), the rebuild's Jan-1 intraday `span` and `chunk_indices` (execution
  filters only; `known` keeps every unit so later spans hold their chunks), ic_measure --run-id,
  and the canary gate judging one run through each tf's proposer unit's completed provenance row.
- `186-31-PLAN.md`: the step runner `services/corpus_rerun.py`, span-major (1d whole history
  first, then per span 1h, 15m, 5m; three spans fit 699 GB at the 534 target, about 600 GB peak),
  the pilot as chunk 0 of the real stage_1d (kept), a detached worktree pin, the data_gate query,
  recovery, and the deletion of the dead orchestrator.
- Plan check: three rounds with gsd-plan-checker. Round three's two blockers (span filter must not
  hide later units from compression_bound; a chunk limit for the pilot) and two warnings (straddling
  chunk wording; run_id on the provenance INSERT, completed rows immutable under the 418 trigger)
  are applied but not yet re-checked. Next session: one more check round, then execute 186-30, then
  186-31, each through /simplify, /review and tools/gate.py.

