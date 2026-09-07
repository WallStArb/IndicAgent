---
status: pending
priority: P2
filed: 2026-09-07
updated: 2026-09-07
source: triage of the 2026-09-04 Workstream-1 recompute failure (ic_engine step 5 OOM-killed 2026-09-07 04:48 UTC)
---

# `alpha.ic.max_cell_rows` guard is checked AFTER the cell is materialized in the cross-sectional chunked path — OOM-kills before it can fire at universe scale

## What happened

The Workstream-1 recompute (`ops_corpus_pipeline_run.sh --from-step 5`, launched 2026-09-04
00:05 UTC to bring the 49 newly regime-routed single-name equities into cross-sectional
measurement, migration 331) ran `ic_engine` for 76.7 hours and was then **OOM-killed by the
kernel** at 2026-09-07 04:48:25 UTC. Confirmed in `/var/log/syslog`:

```
kernel: JTS-DeadlockMon invoked oom-killer: ... order=0
kernel: Out of memory: Killed process 287618 (python) total-vm:102858708kB, anon-rss:19943724kB ... global_oom
```

Exact match to the recorded `step_timings.jsonl` end time (`status: failed`). It died inside
the chunk-accumulation loop of the **`5m / high_bear` equity cross-sectional cell**
(`n_regime_ts: 351816`, `n_chunks: 71`) — the single largest cell, and the one that grew most
from the 49 added equity symbols. The 2026-08-27 run (pre-migration, ~133 equity symbols)
computed this same cell successfully; post-migration (~182 equity symbols) it no longer fits
in 29 GB RAM + 40 GB swap.

## Root cause

`_compute_one_cross_sectional_cell` (`services/ic_engine.py` ~4300+) fetches the cell's
regime timestamps (cheap), then streams `cs_chunk_ts`-sized row chunks into
`Float32ChunkAccumulator` (`X_acc`) + `ret_chunks` + `cmp_chunks` + `bar_ts_chunks`, holding
**every chunk simultaneously**, then concatenates. For `5m/high_bear` equity that is
~351,816 ts x ~182 symbols ~= 64M rows x ~250 float32 feature cols ~= 64 GB, ~1.5-2x that at
the concat/`finalize()` step.

The row-count ceiling guard `_check_cell_size(n_raw, config, ...)` (raises `CellTooLargeError`,
"fails loud rather than silently routing to a degraded algorithm", `alpha.ic.max_cell_rows`
currently `10_000_000`) is called at line ~3614 — **only after `X_raw` is fully materialized**
(`n_raw = len(X_raw)`). The process OOMs during accumulation, long before reaching the check,
so the guard the design relies on to protect this path never fires. `alpha.ic.max_cell_rows`
also has no effect at its current value because the guard is unreachable here.

## Fix options (needs a design decision, not mechanical)

1. **Pre-flight estimate**: before the chunk loop, estimate `n_rows ~= len(regime_timestamps)
   x n_symbols_in_group` (or a cheap `COUNT(*)` on one representative chunk x n_chunks) and
   call `_check_cell_size` on the estimate. Makes the crash-loud guard actually reachable.
2. **Decide what an oversized 5m cross-sectional cell should do**: crash-loud is the current
   stated intent, but that permanently blocks the whole corpus run on a cell that will only
   grow. A pre-registered subsample stride for oversized cross-sectional cells (mirroring the
   per-symbol path's `subsample_min_stride`) keeps the measurement alive — but changes what
   the cell measures, so it needs pre-registration, not a silent default.
3. **Stream to disk / process incrementally** so peak memory is bounded by `cs_chunk_ts`, not
   whole-cell size (the accumulator's original OOM-fix intent, not fully realized for the
   largest cells).
4. **Right-size the box**: whole-cell peak for the worst 5m equity cell is ~100 GB; a machine
   with ~128 GB RAM computes it without swap. Cheapest if 5m cross-sectional stays in scope.

## Immediate workaround applied 2026-09-07 (not the fix)

- Stopped `ib-gateway` + `ollama` containers (dead weight: ingestion down since 2026-08-12
  per todo 366; `ib-gateway`'s `JTS-DeadlockMon` was what invoked the OOM killer).
- Added a 96 GB swapfile (`/swapfile_iceng`, prio 10, total swap 54 -> 150 GB;
  `vm.swappiness=60`) so the 5m equity cross-sectional cells can complete via swap.
- Relaunched `ops_corpus_pipeline_run.sh --from-step 5` — fingerprinting skips the ~76 h
  already computed; only the 5m equity cross-sectional cells + steps 6-8 remain.

The swapfile + swappiness + stopped containers should be reverted once this run lands and a
real fix (option 1+2) is in. Related: todo 356 (same cell, query-plan slowness),
todo 290 (`regime_volatility` obs-matrix ~9.5 GB transient across the worker pool — same
"whole-cell memory not bounded by chunking" family).
