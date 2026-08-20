# 306 - Recover corpus pipeline + live ingestion after the 2026-08-13 disk-full incident

**Filed:** 2026-08-13
**Source:** Terminal disconnect surfaced an investigation into a 768GB disk-full incident
(migration 312 missing `VACUUM`, see `project_disk_full_incident_2026_08_13` memory and
`docs/foundation/timescaledb-compressed-column-migration.md`). The bug itself is fixed (migrations
201/202/312 retrofitted, commit `48bd250fa`) and disk is healthy again (719G free), but the
system is still down as of this filing -- nothing has been restarted or re-run yet.
**Status:** pending, P0 -- three research threads (todos 303/304, `statistical_factor_residual`)
and every other regime-stratified measurement in this project are blocked on this.

**Update 2026-08-20 (re-verified live, not assumed):** substantially resolved by other means
-- `feature_vectors.regime` is 31,204,768/106,268,964 populated and `.regime_volatility` is
31,004,453/106,268,964 populated (not 0 as originally filed), and `indicagent-feature-vector-
pipeline`/`indicagent-feature-vector-writer` are both `active (running)` (10h+ uptime at
check time), not `failed`. The 5-step recovery plan below appears to have already happened
through the 2026-08-15+ corpus pipeline relaunches tracked in
`project_disk_full_incident_2026_08_13` memory, not through this todo directly. Recommend
closing this row and moving it to `completed/` once the current in-flight corpus run + the
queued todo-335 recompute (see that todo's "Recompute status" section) finish and confirm
no residual gap -- don't close blind on a partial re-check.

## Current confirmed state (re-checked 2026-08-13, do not assume it's changed without re-querying)

- `feature_vectors.regime` and `.regime_volatility` are both **0 populated rows out of 69.9M**
  (a 9.66h + 5.3min `regime_writer` run finished its compute and then failed every write because
  Postgres was mid-recovery).
- `indicagent-feature-vector-pipeline.service` and `indicagent-feature-vector-writer.service` are
  both `failed` (SEGV / SIGKILL, `Restart=always` exhausted its burst limit -- need
  `systemctl reset-failed` before they'll restart).
- Live OHLCV ingestion has separately stalled: `market_data_ohlcv` 1m rows went from ~328k/day
  (Aug 10-11) to 7,933 (Aug 12) to 11 (Aug 13), starting **before** the disk-full crash --
  root cause not yet diagnosed, may or may not share a cause with the disk incident.
- `ops_corpus_pipeline_run.sh`'s own step-2 consistency gate failed ("No regime labels found")
  and the script exited -- steps 3-8 never ran.
- Machine was rebooted 2026-08-13 for unrelated reasons after this state was recorded; re-verify
  all of the above first, a reboot may have changed service states.

## Recovery steps (in order -- each gates the next)

1. **Restart the two failed systemd services.** `systemctl reset-failed
   indicagent-feature-vector-pipeline indicagent-feature-vector-writer` then
   `systemctl start` both (or confirm the reboot already did this via `Restart=always`, which
   only fires while systemd hasn't hit its burst limit -- check `systemctl status` first either
   way).
2. **Diagnose the OHLCV ingestion stall independently.** Don't assume it's the same root cause as
   the disk event -- the timing precedes it by about a day. Check `indicagent-ibkr-provider`
   status, IBKR Gateway connectivity, and whatever process/service is supposed to be streaming
   1m bars.
3. **Re-run `regime_writer` for both `regime` and `regime_volatility`** once Postgres is
   confirmed healthy (no `pg_stat_activity` recovery flags, disk headroom checked before
   launching a multi-hour job again).
4. **Decide: resume `ops_corpus_pipeline_run.sh` from step 2/3, or restart the whole run.** Step
   1 (`feature_factory`, `--compute-only`) already completed in the failed 2026-08-12 run --
   check whether its output is still valid before deciding to re-run it too.
5. **Once the corpus pipeline completes**, verify `feature_vectors.regime_volatility` is
   populated, then unblock todos 303/304 (Stage 2/3) and `statistical_factor_residual` (Stage 3)
   -- all three are waiting on exactly this.

## Progress (2026-08-13, post-reboot)

- Step 1 (services): reboot itself reset the systemd restart burst limit --
  `indicagent-feature-vector-pipeline`/`-writer` came back `active (running)` on their own, no
  manual `reset-failed` needed.
- Step 2 (OHLCV stall root cause): diagnosed. `indicagent-ibkr-provider.service` is `disabled`
  and has **never been active** (`ActiveEnterTimestamp` empty) -- this project's live 1m
  ingestion path is the `indicagent-nightly-backfill.timer` (05:00 UTC), not a continuously
  running IBKR streaming daemon. `ib-gateway` container logs show it stuck in a **Second Factor
  Authentication retry loop** since the reboot (login attempt -> 2FA prompt times out after
  ~5-15min -> re-login -> repeat), and the two most recent nightly-backfill runs
  (2026-08-12, 2026-08-13) both logged `nightly_backfill.skipped_concurrent_run` and produced
  near-zero rows -- consistent with the gateway never completing 2FA on either day. **Needs the
  user's phone (IB Key push approval) -- not fixable from the CLI.** Not yet resolved as of this
  writing.
- Step 3 (regime_writer re-run): launched 2026-08-13 18:50 UTC, both passes chained (`regime`
  first, then `regime_volatility`), via `nohup ... & disown` so it survives terminal/session
  boundaries -- same invocation as `ops_corpus_pipeline_run.sh` step 2 (no `--symbols`, defaults
  to full corpus). Confirmed alive and converging cleanly (12 workers, walk-forward HMM) 15s
  after launch. Postgres confirmed out of recovery mode and disk at 720G free before launch.
  Expected runtime ~9.66h (regular) + ~5.3min (volatility), matching the pre-crash run's timing.
  Log: `logs/regime_writer.log`; wrapper exit codes: `logs/regime_writer_relaunch.log`.
- Step 4 (resume vs. restart `ops_corpus_pipeline_run.sh`): not yet decided -- pending step 3
  finishing and a fresh look at whether step 1's 2026-08-12 `feature_factory --compute-only`
  output is still valid.

## Progress (2026-08-14): Step 3's relaunch hit a second, distinct bug -- root-caused and fixed

Step 3's relaunch (above) ran for ~9.5h, converged its HMM compute cleanly the whole time, and
wrote **zero rows** -- `feature_vectors.regime` was still 0/69,897,732 populated when checked.
Root cause, confirmed via `EXPLAIN` (not inferred): `feature_vectors` is a compressed
TimescaleDB hypertable with no usable per-row index on compressed chunks at all -- any
row-level `UPDATE` against it, regardless of predicate selectivity, forces a full `Seq Scan`
per touched chunk (~1000x the cost of the same query against a decompressed chunk, confirmed
via a controlled single-symbol/4,875-row reproduction). `regime_writer.py`'s ~1,000 sequential
per-symbol/tf `UPDATE` calls each hit this, blew the statement timeout on a fixed 30-minute
cadence (585 logged `write_failed` events), and left dead-tuple bloat behind every attempt --
same physical failure mode as this todo's original disk-full incident, this time triggered by
a batch write job instead of a migration. Killed the stuck run (both the client process and a
stray server-side backend that outlived it) once confirmed nothing was being written.

**Fixed this session:** `compressed_hypertable_write_session` / `async_compressed_hypertable_
write_session` (`services/_batch_utils.py`) brackets a batch's writes in one decompress-all ->
write-all (cheap, index-backed) -> recompress-all + bare `VACUUM` session instead of letting
TimescaleDB decompress-and-recompress per call. Wired into `regime_writer.py` and every other
raw/`bulk_update_by_key` writer against `feature_vectors`/`feature_ic_scores` found in the
tree, except `services/ic_engine.py` (deliberately deferred, see todo 307). New CI guard
(`tests/unit/test_compressed_hypertable_write_boundary.py`) catches future raw UPDATEs against
either table that bypass this. Full unit test coverage, `.venv/bin/pytest tests/unit/ -q` green.

**Step 3 needs to be relaunched** now that the write path is actually fixed -- the prior
relaunch's ~9.5h of HMM compute produced nothing durable, so this is a fresh full run, not a
resume.

**Hardening pass same session, post-`/simplify`:** 4 parallel review agents (reuse/
simplification/efficiency/altitude) found and fixed real issues in the first-pass fix above --
collapsed N-per-chunk round trips into one server-side statement per phase, added a
`contextvar` guard so `bulk_update_by_key` now raises immediately if a caller forgets to open
a session for a known compressed hypertable (was previously only caught by the CI grep, which
can't see through `bulk_update_by_key`'s own f-string SQL), and a `..._or_noop` helper
collapsing three independently-hand-rolled `nullcontext()` ternaries into one. Also caught and
fixed a real bug the mock-only unit tests never could have caught: `format('%I.%I', ...)`
inside a psycopg query string collides with psycopg's own client-side placeholder scanner
(`%I` isn't a valid placeholder) and raises `ProgrammingError` at execute time -- found by
actually running the collapsed query against the live DB (not just EXPLAIN), fixed via `%%I`
escaping, re-verified live. Full detail in `services/_batch_utils.py`'s docstrings.

## Progress (2026-08-15): a 6th, undocumented regime_writer attempt crashed on the pre-fix code; relaunched clean

Found via a routine "what's next" check, not proactively tracked -- this todo's own file had gone
stale since 2026-08-14 and didn't reflect what actually happened next.

**Confirmed via live DB query (not the stale file):** `feature_vectors` has grown to 106,268,964
rows (live ingestion healthy, `max(bar_ts)` = 2026-08-13 19:55 UTC). `regime`/`regime_volatility`
sat at ~19.5%/20.3% populated (20.67M / 21.6M rows) -- meaningful progress from whatever combination
of the "5th relaunch" and later attempts actually landed, but nowhere near complete.
**`forward_returns` is far worse: `max(bar_ts)` = 2026-07-28, 16+ days stale** -- older than the
disk-full incident itself. This is the real current bottleneck: `forward_return_writer` (pipeline
step 3) hasn't run since before this incident even started, blocking `ic_engine`, `ensemble_trainer`,
and any IC measurement on newly-added features (including todo 320's 6 fields from earlier today).

**Root-caused a 6th regime_writer crash from this morning, found via log inspection (not
previously logged in this file):**
- A `regime_writer` run started ~11:57 UTC 2026-08-15 (launcher/invoker not identified -- no
  wrapper log, no matching bash history entry; possibly a stray manual relaunch from an earlier
  session today, or a `nohup`'d process from the tail end of 2026-08-14's activity).
- **13:22:04 UTC**: Postgres `FATAL: terminating connection due to idle-session timeout` (confirmed
  via `docker logs timescaledb`, server-side, not inferred) -- exactly todo 318 Bug 1's signature.
- 13:29:25-13:30:37 UTC: cascading `regime_writer.write_failed` / "connection is closed" errors as
  the process kept trying to write on the now-dead connection (`logs/regime_writer.log`).
- 13:30:43 UTC: `regime_writer.fatal_error`, "connection is lost" -- process died. A cluster of
  server-side `FATAL: connection to client lost` at 13:32-13:33 UTC (orphaned worker connections
  finally timing out) closes out the incident.
- **This run was on pre-fix code.** Todo 318 Bug 1's fix (commit `f89363b70`, migration 315)
  landed at **14:29:48 UTC -- about an hour after the crash**, not before it. Nobody relaunched
  `regime_writer` between the crash and this check (over 2 hours later) -- the process was just
  dead and silent the whole time, exactly the failure mode todo 315's fd-rotation finding warned
  would eventually matter ("risks silently losing crash-traceback output... exactly when that
  output matters most" -- in this case the structured JSON error survived fine since it goes
  through `setup_service_logging`'s own handler, not the vulnerable `fd1`/`fd2` path, but the
  *silence* itself -- nobody watching -- was the actual cost).
- **Explains the `compress_chunk` job that blocked this session's earlier migration 316 apply**:
  the crashed session left several `feature_vectors` chunks decompressed mid-write (crashed before
  its own recompress step could run); TimescaleDB's Columnstore/compression policy (job 1065,
  confirmed `scheduled=true` and enabled -- todo 314's mitigation pause was already lifted) picked
  them up and spent 14:47-15:59 UTC recompressing everything, which is exactly the window migration
  316's `ALTER TABLE` sat queued on a lock. Table is now fully compressed again (85/85 chunks,
  verified) -- no lingering damage, just a longer-than-expected wait, now explained rather than a
  mystery.

**Verified safe to relaunch, then did:** disk 691G free / 22% used, load average 0.18-0.58 on 24
cores (idle), Postgres healthy (no recovery flags), job 1065 not currently running, todo 318 Bug 1's
fix confirmed live (`infra.compressed_hypertable_write_session.idle_session_timeout_ms = 0` present
in `config_state`). `regime_writer.py` only fills `WHERE regime IS NULL` (confirmed via
`feature_vector_persistence.py`'s `REGIME_WRITER_OWNED_COLUMN_NAMES` comment), so a relaunch is a
safe incremental resume, not a wasted from-scratch recompute.

**Launched 2026-08-15 12:49 EDT (16:49 UTC)**: `nohup bash scripts/ops/corpus/ops_corpus_pipeline_run.sh
--from-step 2 > logs/corpus_pipeline_orchestrator_20260815_124916.log 2>&1 & disown` -- runs the
full remaining chain: regime_writer (`regime` family) -> regime_writer (`regime_volatility` family)
-> consistency gate -> **forward_return_writer** (the actually-stale step) -> equity_regime_model
-> ic_engine -> ic_shrinkage -> ensemble_trainer -> alpha_publisher. `--from-step 2` skips step 1
(`feature_factory --compute-only`) deliberately -- live ingestion already keeps `feature_vectors`
current, no backfill gap to re-run there. Confirmed alive: orchestrator PID 2186110, `regime_writer.py`
PID 2186137 at 172% CPU (multiprocessing engaged) 5s after launch. A Monitor watchdog is armed
against the orchestrator's own log for step banners / `FAILED` / tracebacks, so a repeat crash
surfaces immediately instead of sitting silent for hours like this morning's did.

**Expected timing** (from the pre-crash 5th relaunch's own measured cost): regime_writer ~9.66h +
~5.3min for the two families combined. `forward_return_writer` and the remaining 5 steps' cost is
not yet measured against the current 106M-row corpus size -- expect this to be a many-hour, likely
overnight run end to end.

**Next, once this completes:** verify `regime`/`regime_volatility` reach full (or expected-plateau,
if some symbols are structurally excluded) coverage, confirm `forward_returns.bar_ts` catches up to
current, then unblock todos 303/304 (Stage 2/3) and `statistical_factor_residual` (Stage 3) -- all
three are still waiting on exactly this, unchanged from the original filing.

## Where

- `systemctl status indicagent-feature-vector-pipeline indicagent-feature-vector-writer`
- `scripts/ops/corpus/ops_corpus_pipeline_run.sh`
- `services/regime_writer.py`, `services/forward_return_writer.py`
- `logs/corpus_pipeline_orchestrator_20260815_124916.log` -- this run's top-level log
- Full incident detail: `project_disk_full_incident_2026_08_13` memory
