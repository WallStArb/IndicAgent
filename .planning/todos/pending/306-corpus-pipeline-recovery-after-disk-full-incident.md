# 306 - Recover corpus pipeline + live ingestion after the 2026-08-13 disk-full incident

**Filed:** 2026-08-13
**Source:** Terminal disconnect surfaced an investigation into a 768GB disk-full incident
(migration 312 missing `VACUUM`, see `project_disk_full_incident_2026_08_13` memory and
`docs/foundation/timescaledb-compressed-column-migration.md`). The bug itself is fixed (migrations
201/202/312 retrofitted, commit `48bd250fa`) and disk is healthy again (719G free), but the
system is still down as of this filing -- nothing has been restarted or re-run yet.
**Status:** pending, P0 -- three research threads (todos 303/304, `statistical_factor_residual`)
and every other regime-stratified measurement in this project are blocked on this.

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

## Where

- `systemctl status indicagent-feature-vector-pipeline indicagent-feature-vector-writer`
- `scripts/ops/corpus/ops_corpus_pipeline_run.sh`
- `services/regime_writer.py`
- Full incident detail: `project_disk_full_incident_2026_08_13` memory
