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
  calendar keyed by session_id, pre-2000 1d sessions reported, names without a start or sessions
  refused unless held by a 1d empty-history span of the era's policy primary) with the pre-2016
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

## 186-30 landed (2026-11-05)

Run identity is on main: migration 578 (corpus_run with immutable identity and append-only
caveats, corpus_run_step, provenance_batch.run_id moving only on a takeover to started), the
rebuild's run_id, Jan-1 intraday span and chunk_indices (execution filters only), ic_measure
--run-id, and the canary gate requiring --run-id over the APR tf list and refusing any tf whose
proposer unit is not completed under that run (with tests). Summary:
`.planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-30-SUMMARY.md`.
Left: 186-32 (migration 579, data gate) and 186-31 (step runner, deletes the dead shell
orchestrator).

## 186-32 landed (2026-11-05)

Migration 579 seeds the nine infra.corpus_rerun.* keys (read through
`services/corpus_rerun_apr.py`); `services/corpus_rerun_data_gate.py` `run_data_gate` measures
every NYSE session per compute_1d name-year (1d bar, 5m of the policy pair at
min_session_bar_fraction of the session's own slots or an empty-history span) and returns the
result for the runner to persist. Live dry run (87 s): fails; IBKR era 79 at depth, 482 partial,
574 none of 1,135 names; Alpaca era 848 / 641 / 3 of 1,492, where the partials are mostly thin
names with no-trade slots (a lead decision on the fraction); 10 names without a proven start.
Summary: `.planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-32-SUMMARY.md`.
Left: 186-31.
