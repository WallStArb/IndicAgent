---
status: completed
priority: P1
filed: 2026-07-25
closed: 2026-07-29
source: live diagnostic during todo 092's corpus recompute — 100% single-core CPU, zero
  active Postgres queries, observed directly via `top`/`ps`/`pg_stat_activity` while the
  15m `low_bull` cross-sectional cell ran
---

## Resolution (2026-07-29)

Independently re-diagnosed (same evidence: 24-core box at load-avg 1.5, one thread pinned
90%+, the 15m `high_bear` cell alone measured at 2h08m serial) during a live equity-scoped
`ic_engine.py --symbols <49 equity symbols>` run (the same run [167](../pending/167-equity-cross-sectional-vs-symbol-hmm-never-falsifier-tested.md)
needs). Fixed via `ConfigService.set()` (not a migration — this repo's config write path):
`alpha.ic.cross_sectional_bootstrap_threads.{15m,1h,1d}` raised from `1` to `8`, changed_by
`brandon`, reason cites this todo's measurement. `.1d`/`.1h` raised alongside `.15m` rather
than left at the todo's "lowest priority, likely fine" guess — same unmeasured-`[conventional]`
shape of assumption, no reason to leave two of three unverified.

Did not run the formal wall-clock/RSS benchmark this todo's Fix section specified (step 1) —
the live run itself is the benchmark; re-verify actual `15m`/`1h` cross-sectional wall time
against pre-fix per-cell timings (already in `logs/ic_engine.log` from the run this was found
in) once the equity-scoped run completes post-[198](../completed/198-ic-engine-fingerprint-gate-false-invalidation.md).
`162-HUMAN-UAT.md` item 3 still needs its own update per this todo's step 5 — not done here,
separate action.

# `alpha.ic.cross_sectional_bootstrap_threads.15m=1` is empirically stale — this is 162-HUMAN-UAT.md item 3, now with live evidence it fails

## Finding

Todo 133 (closed 2026-07-23 via Phase 162-02) converted `cross_sectional_bootstrap_threads`
from a scalar to a per-tf APR dict, seeded `5m=6, 15m=1h=1d=1`. The `.15m`/`.1h`/`.1d`
`config_schema` descriptions all state: *"These cells finish in minutes serially; threading
only adds dispatch overhead."* Per that same todo's own closing note, this was **never
validated by an actual timing comparison** — it's tracked as open item 3 in
`.planning/phases/162-ic-engine-corpus-pipeline-throughput-incremental-recompute-t/162-HUMAN-UAT.md`,
still `status: partial`, still `result: [pending]`.

Live evidence from today's todo 092 recompute run (`ic_engine.py`, PID 1633901) shows the
"minutes" assumption is now **false** for 15m, not just unverified:

- `top -bn1 -p 1633901`: **100.0% CPU (one core) of 24 available**, 68 threads, `R` state.
- `pg_stat_activity`: zero active queries at the same moment — this is pure single-threaded
  Python/numpy compute, not I/O wait.
- `logs/ic_engine.log`: the 15m `high_bear` cell (118,125 timestamps, 24 chunks) took
  **121 minutes**. The 15m `low_bull` cell (180,704 timestamps, 37 chunks, the largest 15m
  cell) ran well over an hour before this todo was filed.

The universe grew 58→80 symbols (2026-07-01) and the feature count grew to 171 (Phase
142.5/151/163) since the original 6-thread benchmark (migration
`239_ic_engine_cross_sectional_bootstrap_threads.sql`) was scoped — that benchmark measured
only the 5m worst case, explicitly assuming 1d/1h/15m stayed cheap. That assumption no longer
holds for 15m at today's corpus scale.

## Fix

Same methodology as the original 5m benchmark (todo 133 / migration 239) — measure, don't
guess:

1. Benchmark `alpha.ic.cross_sectional_bootstrap_threads.15m` at `max_workers=1` (current)
   vs. `4`/`6` on a real 15m cell at today's scale (80 symbols, 171 features), recording both
   wall-clock time and peak RSS (same two numbers the 5m benchmark recorded: ~0.99h @ 6
   threads vs ~3.72h serial, 13.6GB peak RSS).
2. If a real speedup is confirmed with acceptable memory margin, update the
   `alpha.ic.cross_sectional_bootstrap_threads.15m` APR default via a new migration (same
   pattern as 239), with `changed_by`/`reason` citing this todo and the live measurement.
3. Spot-check `.1h` the same way — it finished all 9 regimes in ~52 min this run (not
   obviously broken), but wasn't benchmarked either; confirm it's actually fine rather than
   assuming from one run's aggregate time.
4. `.1d` cells are consistently small (hundreds to low thousands of rows per regime) — lowest
   priority to re-check, likely still correctly served by `threads=1`.
5. Update `162-HUMAN-UAT.md` item 3 with the result (pass/fail against its stated
   expectation) once the benchmark runs — this todo and that UAT item are the same gap,
   don't track it in two disconnected places going forward.

## Why this wasn't fixed inline

Found while a real, multi-day production corpus recompute (todo 092) was actively running on
this host. `alpha.ic.cross_sectional_bootstrap_threads.*` is loaded once into
`IcEngineConfig` at `ic_engine.py` process startup, not hot-reloaded mid-run — so changing it
now is safe (won't disturb the in-flight run) but running a competing benchmark script
alongside a P0 multi-day recompute would contend for the same CPU cores this todo is trying
to free up. Do this once the current recompute finishes, using the finished run's own
`ic_engine.log` per-cell timings as a starting cross-check before spending a dedicated
benchmark run.

## References

- `.planning/todos/completed/133-cross-sectional-bootstrap-threads-not-per-tf.md` — the
  original per-tf conversion; this todo is its unfinished verification step, now with a
  concrete failure to point at
- `.planning/phases/162-ic-engine-corpus-pipeline-throughput-incremental-recompute-t/162-HUMAN-UAT.md`
  item 3 — the same open gap, tracked at the phase level
- `production/migrations/239_ic_engine_cross_sectional_bootstrap_threads.sql` — original
  6-thread 5m-only benchmark this todo's fix repeats for 15m
- `services/ic_engine.py:2542,2620,2644` — `cross_sectional_bootstrap_threads[tf]` call sites
- `logs/ic_engine.log` (2026-07-25 entries) — the live per-cell timings this finding is based on
