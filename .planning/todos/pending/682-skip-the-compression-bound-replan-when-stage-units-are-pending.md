---
status: pending
priority: P3
filed: 2026-11-26
source: pilot eca9e854 timing replay (indicagent-fc, lead ruling 2026-11-26); review by indicagent-db
---

# Skip the compression_bound replan at the end of a stage call when units are pending

## What

`run_rebuild_stage` ends every call by planning the whole corpus again (`compression_bound`,
`services/backfill_feature_factory.py` around line 1854) so it can compress the chunks whose units are all
complete. When any unit failed or is pending the result is `compression: "partial: units pending"` and
nothing needs freeing, but the replan still runs. On 2026-11-26 it cost a fixed 600 s per stage call with
`chunks_compressed` 0 both times: pilot run eca9e854, pass 1 last unit loaded 17:45:01.99 and `rebuild_complete`
17:55:04.22 (602.2 s); pass 2 last unit loaded 18:03:22.62 and `rebuild_complete` 18:13:22.05 (600.0 s).

## Why it matters

- Each resume of a stage costs ten minutes that no unit caused.
- The pilot's per-unit time divides the stage call's wall time by the units that call loaded, so the tail
  inflates it: 9.6 h projected for stage_1d against about 6.8 h without the two tails (the pilot disclosure in
  `docs/operations/guarded-run-runbook.md` labels the recorded figure a pessimistic bound for this reason).
- For stage_1d itself (one call over every unit) the tail is negligible; the cost is on resumed stages and
  on the pilot's measurement.

## Goal and scope

End state: a stage call that has failed, pending or out-of-scope units skips the replan and reports the same
`compression` status it reports today; a call whose units are all complete still compresses exactly as before.
Option to weigh: cache the bound across calls instead of skipping. Measure the replan's own cost first
(where the 600 s goes: the planning reads, not the compression).

## Constraints and gates

- Edits `services/backfill_feature_factory.py`, a module the fingerprinted rebuild imports. It moves
  `rebuild_code_key()`, so it never lands while a corpus run is live or resumable: it waits for stage_1d and
  feature_complete to be recorded and lands in the post-stage re-pin window.
- A test that a stage with a failed unit does not call `compression_bound`, and one that a fully complete stage
  still compresses the same chunks.
- Gates: /simplify, /review, `pytest tests/unit/ -n auto`, `rebuild_code_key()` printed before and after.
