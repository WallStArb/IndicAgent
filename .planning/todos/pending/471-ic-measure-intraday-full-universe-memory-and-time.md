---
status: pending
priority: P2
filed: 2026-09-30
source: plan 186-14 pass 2, real 15m dry run
---

# ic_measure block width, threads and which tfs a corpus run may measure

## What

`alpha.ic.feature_block_columns` is one key for every tf, pinned in the run's APR hash; results are bit-identical at any width. At the stage 2 universe the memory is arithmetic (sizes in todo 667): 1d fits at any width, 1h at width 4 to 8, 15m only at width 4 or less, 5m at no width (the dense targets of three horizons are 54 GB).

## Ruling (lead, 2026-11-24)

1. Scope-1d pin: `alpha.ic.feature_block_columns` = 16 and `ic_tfs` = 1d only (block 9.2 GB, targets 2.3 GB, long form about 3 GB on 59 GiB).
2. No 5m and no 15m in any `ic_tfs` until the measure holds a tf in time chunks (todo 667). 1h is allowed at width 4 only if wanted. The scope-all pin is decided later with measured numbers.
3. Prerequisites of the scope-all pin, neither blocking the scope-1d pin: 667 (time-chunk mode) and 668 (checkpoint grain, todo 470 merged).

## Done when

After the block 2 rerun has finished and no heavy job is live: `ic_measure --tf 1d --dry-run --symbols <the 25 pilot names>` at widths 4, 8, 16 and 32 with peak RSS sampled, recorded here with bytes per grid cell and the digest-pass share; the NYSE-calendar grid sizes (computed 2026-11-24: 5,609 sessions from 2003-09-10 to oos_start; 1d 5,609 bars, 1h 39,110, 15m 145,222, 5m 435,666) are in todo 667. Then close this todo with the pinned width written into the scope-1d run's APR.

## Readiness for the scope-1d IC measure (2026-11-27, run dcb7caa4-b1d0-4736-be54-197c9e521dce)

Written while `stage_1d` runs; nothing here was run (a preflight refuses while the stage is live, see below).

- Needs from the stage: `corpus_run_step` rows `pilot` and `feature_complete` `completed`, `ic_measure` not completed (today: `data_gate`, `pin_gate`, `pilot` completed, `stage_1d` started). The run worktree HEAD must equal its recorded `code_commit` (86161748e, which contains the sweep recorder of ed2b16c9b) and `rebuild_code_key()` must start with the expected prefix (STATE names it: 487f4ab434df). `alpha.ic.feature_block_columns` reads 16 now. Also required by the launcher: the IDENTICAL block 2 line, `memtester_clean`, fresh member verdicts (`verdict_preflight`), the 01:00 to 05:00Z window closed, no corpus run, `ic_measure` or rebuild process live.
- Ledger gate (not mechanical): ledger 2026-11-24f says the `ic_measure`, `d19_bound` and `canary` steps wait for the sweep-cell writer (todos 670 and 671, now built and on main) and that the first IC pass is ledgered with its cell count before it runs. The draft of that line is in `269d63c44`; the lead records it, and the sweep recorder's dry run prints the `n_looks` to declare. Ledger 2026-11-25c (regime columns stay out of the sweep) is a draft awaiting the owner.
- Launch: `cd /home/bg/dev/indicagent && git pull --ff-only`, then `PREFLIGHT_ONLY=1 bash scripts/ops/ic_measure_launch.sh dcb7caa4-b1d0-4736-be54-197c9e521dce 487f4ab434df` (prints the verdict, no host gate, no timers), then `setsid -f bash scripts/ops/ic_measure_launch.sh dcb7caa4-b1d0-4736-be54-197c9e521dce 487f4ab434df`. Optional first, for this todo's measurement: `RSS_CHECK=1 RSS_SYMBOLS_FILE=<25 names> bash scripts/ops/ic_measure_launch.sh <run> <prefix>` (a `--dry-run` of 25 names under the watchdog, peak RSS recorded in the status file, then it stops). PREFLIGHT_ONLY reads only (psql selects, `rebuild_code_key()` imported in the run worktree, `pgrep`), but it still refuses while the stage is live, so it cannot confirm anything before the stage ends.
- Timers: the stage launcher holds the blocking timers on every exit and `ic_measure_launch.sh` re-quiesces (idempotent: it keeps the first record of what was enabled) and releases only after a clean exit; any other exit leaves them held with the resume command in the status file. Defect to fix before launch: its two failure branches (`quiesce failed`, `cd worktree`) call `--release`, which would re-enable the timers between `feature_complete` and the IC measure and so let bars restate under a run whose features are already built (the lead ruling of 2026-11-27); they should hold instead.
- Memory floor: the launcher takes the hard-coded 40 GiB of `guarded_run_common.sh` (`MEM_FLOOR_KB`), at the host's resting MemAvailable (38.6 to 40.7 GiB), so it would refuse more often than not. Propose the stage's pattern: an APR key `infra.run_guarded.mem_floor_gib.ic_measure` with bounds 8 to 512, read like `stage_floor_kb`, seeded from the measured peaks rather than guessed. The arithmetic (ruling above: block 9.2 GB, targets 2.3 GB, long form about 3 GB, about 15 GiB plus the interpreter) is the lower bound; the `stage_1d` peak (cell pending in the budget table, about 12:15Z) and the `RSS_CHECK` figure set the seed. No change before then.
- Duration: unmeasured. No full-universe 1d IC measure has run; the `RSS_CHECK` dry run gives bytes per grid cell, not time, and the first step's wall time becomes the figure (the `run_resource` start and end timestamps record it).
- Writes: `feature_ic_scores` rows (POOLED unstratified proposer units at each horizon of `alpha.ic_measure.horizons`, plus the `regime_volatility` job), the report `<spool>/corpus_rerun/ic_measure_<run>.json`, the `corpus_run_step` `ic_measure` row (pin checks, adopted units, pooled lookaheads), the status line with `peak_rss_mb`, and the `run_resource` gauges (`run_resource_ic_measure_launch_ic_measure.prom`). Closing this todo needs the pinned width 16 on the run's APR plus the recorded peak RSS and bytes per grid cell.
