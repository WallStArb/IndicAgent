---
claimable: true
status: pending
objective: O1
priority: P1
filed: 2026-11-28
source: indicagent-b9, IC sweep readiness review (independent review of the todo 671 checklist)
---

# A guarded launcher for the IC sweep steps, and a dry-run report that can show its values moved

## What

The steps between `feature_complete` and the first counted 1d sweep (todo 671's checklist) have three gaps that only code closes:

1. No guarded path. The 670 check, the two recorder dry runs and the recorder's real blocks are heavy, but nothing runs them under the DIMM watchdog, the host and memory gates and the one-heavy-job rule (`run_guarded` in `scripts/ops/guarded_run_common.sh`), and nothing holds the capture timers while the recorder reads bars. `ic_measure_launch.sh` releases the timers on a clean exit, so a recorder block run after it reads bars a nightly could have restated since the dry runs (the 2026-11-27 ruling holds the timers from `feature_complete` to the IC measure for exactly this).
2. Pilot gate (b) cannot fail on values. The recorder's dry-run report holds counts and name lists only (`batch_attempts`, `excluded_*`, `unmeasured`), so two dry runs with different IC values compare identical. The gate exists to show the measurement is deterministic on one pin.
3. The 670 output JSON records `stepm_sha256` but not the code commit the spec asks for.

## Scope

- `scripts/ops/ic_sweep_launch.sh <mode> ...`, sourcing `guarded_run_common.sh`: modes `stepm-check`, `dry-run` and `record` (the last passes `--horizons` and `--declared-n-looks`). Every mode runs through `run_guarded` with its own APR memory floor key (`infra.run_guarded.mem_floor_gib.ic_sweep`, a migration with a provenance note), refuses beside a live heavy job, and runs from a detached worktree it checks is clean and an ancestor of origin/main. `dry-run` and `record` need the blocking timers held. When they are already held on entry (a run awaiting its IC measure: the stage's hold), the launcher takes no hold and releases nothing on exit, so it cannot open the window the 2026-11-27 ruling closes; only when they are not held does it take a fresh hold (`hold_timers`) and release it on exit (todo 671, item 9). A test covers the inherited-hold path (nothing released) and the fresh-hold path.
- `services/ic_sweep_recorder.py`: the report gains, per block, the spec hash and a SHA-256 of the long series' dates and values (canonical bytes), so `cmp` of two dry-run reports tests the values. No change to what is recorded; the dry run stays write-free.
- `scripts/research/stepm_sweep_scale_check.py`: the JSON records `code_commit` (HEAD of the worktree, refused when dirty).
- Tests: the launcher's pure judges (sourced, as `ic_measure_launch.sh`'s are); the digest moves when one value moves and not with name order; the 670 JSON carries the commit.

## Boundaries

No edit to `services/ic_measure.py`, `src/intelligence/research/` or `src/intelligence/statistics/` (so no `repro_frozen`); the recorder edit is outside the rebuild code key (check `writer_code_modules()` before and after). Never beside a live counted run or the successor's stage.

## Done when

The three gaps are closed and tested, and the run section of `docs/research/draft-ledger-2026-11-27a-first-ic-sweep.md` uses the launcher for steps 1, 3 and 6.
