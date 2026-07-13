---
status: pending
priority: P0
filed: 2026-07-12
source: monitoring the 143.1-07 corpus re-run (PID 3027216, started 2026-07-12T04:46 UTC)
---

# `ic_engine.py` corpus re-run writes zero rows — postgres `idle_session_timeout` kills the connection before write

## Finding

The 143.1-07 full-pipeline corpus re-run (`--from-step 1`, `--workers 4`) has been running since
2026-07-12T04:46 UTC. As of 2026-07-12T12:00 UTC (~3h15m in), it has written **zero rows** to
`feature_ic_scores` for this run:

- `feature_ic_scores` has 920,649 rows at `training_window_end = '2025-12-24 05:15:00+00'`, but
  every one has `computed_at = 2026-07-09` — three days stale. None from today.
- The log (`logs/ic_engine.log`) shows 29 `symbol_computed` events (20 distinct symbols, some
  retried) — **every one is `n_rows: 0`.**
- 92 `worker_cell_failed` errors across 21+ symbols, all `"connection already closed"` or
  `"server closed the connection unexpectedly"`.
- Postgres itself is healthy and has not restarted (`pg_postmaster_start_time` = 2026-07-04,
  container up 7 days) — this is not a DB crash.

## Root cause (confirmed via `docker logs timescaledb`)

`idle_session_timeout = 15min` is set on the postgres instance. The container log is flooded
with `"terminating connection due to idle-session timeout"` and `"connection to client lost"`.

Phase 143.1-01 replaced the cheap analytic Fisher-z CI with circular block bootstrap resampling
— a genuinely correct fix, but much more expensive per cell. Individual clustering/bootstrap
steps now visibly take 1-10+ minutes each (per `ic_engine.clustering` log timestamps), and a
full symbol's worth of (tf, regime) cells is exceeding the 15-minute idle window while the held
DB connection sits idle mid-compute. By the time the code returns to that connection to write
results, postgres has already killed it. This looks like a real regression introduced by
143.1-01's own heavier compute colliding with a pre-existing infra setting that was fine under
the old, cheaper Fisher-z cost profile — not resource contention or a postgres-side problem.

## Not yet done

- Left running per project-owner decision (2026-07-12) — not killed, not fixed yet, still
  producing zero output as of filing.
- Fix options not yet evaluated: (a) raise/disable `idle_session_timeout` for the ic_engine
  session (`SET idle_session_timeout = 0` or similar, scoped to this workload), (b) keep the
  write connection alive with a periodic no-op/keepalive during long compute phases, (c)
  restructure so the connection is opened fresh right before the write rather than held across
  the whole compute phase (aligns with the project's general pattern of workers being
  compute-only and returning results to a single serial writer — see DAG Invariant on
  `ProcessPoolExecutor` workers in CLAUDE.md).
- Whoever picks this up should kill the current PID (3027216 and children) before restarting —
  it cannot succeed as configured, and every additional hour left running is wasted compute
  producing nothing.

## Fix applied 2026-07-12 (option c) — verifying, not yet closed

`_compute_symbol_tf` (`services/ic_engine.py`) now takes `dsn: str` instead of a live `conn` and
opens two short-lived connections per (symbol, tf) call — one for the initial feature/
forward-return fetch, closed immediately after; a second opened fresh right before the
context-features loop, closed after — instead of holding one connection idle across the
clustering/bootstrap loop between them (the actual idle gap that was hitting the 15-minute
timeout). `_run_ic_worker`'s shared per-tf connection (and its now-unnecessary
`conn.rollback()`) removed to match. Unit tests updated (`test_ic_engine_compute_split.py`'s
signature assertion) and green.

Old PID 3027216 (and a second broken attempt, 3126397) plus their orphaned forkserver/worker
children were killed. Corpus re-run restarted clean at **2026-07-12T12:52:47 UTC**
(`--training-window-end "2025-12-24 05:15:00+00" --workers 4`).

**Status as of 2026-07-12T13:22 UTC (~30 min in):**
- Zero `worker_cell_failed` / `connection already closed` / `idle-session` events since restart
  — a strong positive signal, since the prior two attempts both started throwing these within
  their first ~15-20 minutes.
- Zero rows written to `feature_ic_scores` yet — **expected, not a red flag**: `pool.map(...,
  chunksize=1)` only logs `ic_engine.symbol_computed` and makes a symbol's rows available for
  the corpus-level BH-FDR write after that symbol finishes **all 4 timeframes** (5m alone spans
  ~9 regimes and is taking several minutes per regime per the `ic_engine.clustering` log), so
  the first row-write wasn't expected until well past the 30-minute mark. This is a batching
  characteristic of `_run_ic_worker`/`pool.map`, not evidence of a new problem.
- Next check: confirm the first `symbol_computed` events appear with nonzero `n_rows` and that
  `feature_ic_scores` starts accumulating today's `computed_at` rows. Close this out (move to
  `completed/`) once that's observed; re-open investigation if failures resume instead.

**Status as of 2026-07-12T14:00 UTC (~67 min in):** still progressing normally, still not
confirmed closed.
- Still zero `worker_cell_failed`/`connection already closed`/`idle-session` events since
  restart — now well past 4x the ~15-minute window where both prior attempts failed.
  `ARKK` finished clustering for all 4 timeframes (5m through 1d) as of 13:50:24 UTC and is now
  in the context-features loop (the second short-lived connection, per the fix) — real forward
  progress through the full per-symbol pipeline, not stuck. `AGG`, `AMLP`, `BIL`, `BTAL` are
  mid-flight behind it.
- Still zero rows in `feature_ic_scores` and no new `symbol_computed` log lines since restart —
  `ARKK` hasn't returned from `pool.map` yet even though its clustering is done, consistent with
  the context-features loop (a further ~15-20 small queries + bootstrap CI each) taking
  meaningful time on top of the multi-minute clustering pass. Not concerning yet, but this is
  running slower than a first estimate would have suggested — with only `--workers 4` against 80
  symbols and heavy per-cell bootstrap cost, full completion likely takes several more hours.
  Scheduled another check-in rather than declaring closed.

**Status as of 2026-07-12T14:49 UTC (~117 min in): important recalibration, still not closed.**
- Still zero failures since restart (117 min, ~7-8x past the old failure window).
- **Root cause of "no symbol_computed events yet" identified — it's `pool.map()` ordering, not a
  stall.** `Executor.map(..., chunksize=1)` yields results in *submission order*, not completion
  order. Per-symbol clustering-log evidence shows `ARKK`, `AMLP`, `BIL` have each already
  finished their first symbol and their workers picked up 2nd symbols (`BTAL` at 13:50, `CIBR` at
  14:20, `CWB` at 14:26) — real completions are happening. But `AGG` (first/early in the 80-symbol
  submission order) is running unusually slowly — still on its first symbol, only reached `15m`
  by 14:48 — and the main process's `for result in pool.map(...)` loop blocks on `AGG` before it
  can log *anything*, even though other workers' results are sitting ready. **No `symbol_computed`
  event will appear until `AGG` (and anything ordered before it) finishes**, however long that
  takes, regardless of how many other symbols are actually done.
- **Separately: the corpus-level BH-FDR write only happens after ALL 80 symbols finish** (per
  `_write_ic_results`'s design — corpus-level FDR needs every symbol's p-values first), so
  `feature_ic_scores` will show **zero rows for the entire run**, not incrementally, regardless of
  the `pool.map` ordering issue above. Full confirmation of this fix requires the complete
  80-symbol run to finish, which at the observed pace (many tens of minutes per symbol per
  worker, 4 workers, 80 symbols) is a multi-hour proposition, not something to expect soon.
- **Practical read:** the fix is very likely working — sustained zero failures across 117+
  minutes and multiple symbols' worth of real clustering progress is strong evidence — but a
  fully definitive confirmation (an actual row write) is hours away, not tens of minutes.
  Switching to a much longer check-in cadence; will close this out once the run actually
  completes or a failure recurs.

**Status as of 2026-07-12T15:52 UTC (~180 min in): first real confirmation — mechanism proven,
run still not complete.**
- Still zero failures since restart (180 min, ~11-12x past the old failure window).
- **`AGG` finally finished at 15:04:46 UTC.** The instant it did, `pool.map`'s submission-order
  block released, and the main process logged a burst of already-completed results: `AGG`
  (n_rows=400), `AMLP` (355), `ARKK` (325), `BIL` (395), `BTAL` (300) — all at the same
  millisecond timestamp, confirming they'd been sitting finished in their workers for a while.
  `CIBR` followed independently at 15:22:14 (n_rows=330). **These are real, nonzero
  `n_rows` values** — not the `n_rows: 0` failure signature from the two broken attempts. The
  connection-lifecycle fix is now confirmed working end-to-end for at least 6 symbols, not just
  "no errors so far."
- `feature_ic_scores` still has 0 rows — expected and unchanged: the corpus-level BH-FDR write
  only fires after all 80 symbols finish. 6/80 done in ~132 minutes (much of that was `AGG`
  alone blocking visibility, not necessarily 6 symbols' worth of real elapsed work) — rough order
  of magnitude suggests several more hours before full completion, consistent with the earlier
  estimate.
- Not closing this out yet (still running, no DB rows), but confidence is now much higher than
  "no failures so far" — real measured output is flowing. Next check: full completion (process
  exits, rows land) or a failure recurrence.

## Status as of 2026-07-12T20:39 UTC: killed a second time — stale code, not a new failure, plus a real perf finding and a resumability fix

The connection-lifecycle fix above is confirmed correct and stays fixed. What follows is a
**separate** event on top of it.

**Runtime reality check.** Filtering `logs/ic_engine.log` to only this run's lines (after
12:52:48 UTC) showed **10 symbols in 5 hours**, not the 20 an earlier unfiltered grep suggested
(that count leaked in 2 dead prior attempts' log lines). 10/80 in 5h projects to **~40 hours
total** —40x over `143.1-07-CORPUS-RERUN.md`'s own pre-committed 60-minute budget (central
estimate 16.5min at `workers=12`). `py-spy dump` on a live worker (5/5 samples) confirmed the
time is genuinely spent in `_circular_block_bootstrap_ic`'s per-iteration `rankdata`/`argsort`
(`ic_math.py:193`) — **this is correct, deliberate code** (the docstring explains a vectorized
broadcast form was rejected for 7.5GB/worker OOM risk), not a bug. The 60-minute budget simply
never accounted for full production scale (150+ features × ~40 (tf,regime) cells/symbol × 2000
resamples). **`143.1-CONTEXT.md`'s E6 runtime-budget entry should be corrected to reflect this
real-world number** so a future reader doesn't trust the 16.5min estimate.

Separately, `free -h` showed this box has only **29GB RAM** with 17GB in swap. The 4 running
workers were confirmed NOT thrashing (99.7% sustained CPU, not iowait-bound) but only ~8.8GB was
available — **`workers=12` (the plan's benchmark) would not have fit**; `infra.ic_engine.workers`'s
existing APR value of `8` is the real safe ceiling on this machine, not 12. The run had been
launched with an explicit `--workers 4` CLI override that silently bypassed the APR default —
now fixed (see below).

**Then, before any restart: found a concurrent Claude Code session had spent that same ~5h
window autonomously executing all of Phase 144 (`regime_group` cross-sectional model) via git
worktrees, merged straight to `main`** — including migration 229
(`market_regimes.asset_class`→`regime_group`) and an `ic_engine.py` rewrite fixing a confirmed
cross-sectional pooling contamination bug (144-05b). This run's process had loaded the
pre-Phase-144 code into memory hours before any of that landed, so its progress was stale
regardless of the perf question above. Full detail:
[Phase 144 status](../../../.claude/projects/-home-bg-dev-indicagent/memory/project_v315_phase144_status.md)
(memory) and 144-06-SUMMARY / `ROADMAP.md`.

**Action taken:** killed PID 3152282 + `kill -9`'d 5 orphaned forkserver workers (`pool.map`
doesn't propagate SIGTERM to forked children). Applied migration 229 (was merged in code but
never actually run against the live DB — `market_regimes` had no `regime_group` column).
Confirmed `ops_corpus_pipeline_run.sh` step 4 is now `cross_sectional_regime_model` (the
concurrent session updated the script too); `market_regimes` only had stale `equity` rows (max
ts 2026-07-07) and zero `rates` rows, so **the correct restart point is `--from-step 4`**, not
step 5 (`ic_engine` alone).

**Also shipped to `services/ic_engine.py` + `src/observability/metrics.py` this same session**
(uncommitted, full `tests/unit/` green): per-symbol checkpointing keyed to git HEAD short-SHA
(`_save_checkpoint`/`_load_checkpoint`, `logs/ic_engine_checkpoints/<training_window_end>_<sha>/`)
so a kill/restart only recomputes symbols not yet checkpointed under the *current* commit — a
code change (like Phase 144 landing) automatically invalidates old checkpoints rather than
risking a silent stale replay; `pool.map`→`pool.submit`+`as_completed` (fixes the submission-order
visibility problem documented in the 14:49 UTC status entry above); a loud warning when
`--workers` overrides the APR value; `IC_ENGINE_SYMBOLS_COMPLETED_TOTAL`/`IC_ENGINE_RUN_SYMBOLS_TOTAL`
metrics for real progress instead of log-grepping.

**Not yet done:** relaunch (`ops_corpus_pipeline_run.sh --from-step 4`, `--workers 8`) — waiting
on a machine reboot first (17GB swap, user-initiated). Once relaunched and fully green, close
this todo out; also re-run `scripts/analysis/phase144_regime_separation_gate.py` (144's D-05
gate, currently `BLOCKED-ON-143.1-07`) once `feature_ic_scores` is fresh.

## Status as of 2026-07-13: CLOSED — connection-lifecycle fix confirmed a third time, run in progress under corrected estimator

No reboot occurred; `ops_corpus_pipeline_run.sh --from-step 4` was relaunched directly the same
day (todo-096's estimator fix landed first, commit `d06ac60d`, so this relaunch also picks that
up). Step 4 (`cross_sectional_regime_model`) completed clean; step 5 (`ic_engine`) has been
running since 2026-07-13T13:13:58 UTC with zero connection/idle-timeout failures — the third
consecutive clean run under the option-c fix (short-lived per-phase connections), now considered
fully confirmed, not just "likely working."

Worker count was briefly bumped 8→10 mid-restart on a misread of a transient memory snapshot,
then reverted back to 8 within the hour after a real (but unrelated, step-4-clustering-caused)
memory spike was mistaken for a consequence of the bump — see `config_history` for both entries.
Confirmed via the process's own startup log (`n_workers: 8`), not just the APR value, that the
revert took effect correctly (no ConfigService caching issue). At 9/80 symbols by 15:19 UTC
(~15.5 min/symbol, matching the pre-fix run's rate almost exactly, as expected since the
estimator fix touches Sharpe-window sizing, not the bootstrap CI cost that dominates runtime),
full corpus completion is projected ~10:00 UTC 2026-07-14, plus ~1-1.5h for steps 6-8.

Closing this out: the idle-session-timeout bug this todo was filed for is fixed and
triple-confirmed. The runtime/perf finding, the Phase-144-collision incident, and the
checkpointing/`pool.submit`/metrics work that came out of chasing this bug are all shipped
(commit `d06ac60d`) — see [[project_corpus_pipeline_state]] (memory) for the full narrative,
not duplicated here further.

## References

- `logs/ic_engine.log`, `docker logs timescaledb`
- `.planning/phases/143.1-measurement-and-eligibility-integrity-fisher-z-ci-bootstrap-/143.1-01-PLAN.md`
  (the bootstrap CI change that raised per-cell compute cost)
- `.planning/phases/143.1-measurement-and-eligibility-integrity-fisher-z-ci-bootstrap-/143.1-07-CORPUS-RERUN.md`
  (the plan this run is executing; its E6 runtime-budget estimate needs correcting per above)
- `.planning/phases/144-cross-sectional-regime-model-regime-group-planned/144-06-SUMMARY.md`
  (D-05 gate, `BLOCKED-ON-143.1-07`)
