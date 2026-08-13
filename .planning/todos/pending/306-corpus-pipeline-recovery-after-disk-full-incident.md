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

## Where

- `systemctl status indicagent-feature-vector-pipeline indicagent-feature-vector-writer`
- `scripts/ops/corpus/ops_corpus_pipeline_run.sh`
- `services/regime_writer.py`
- Full incident detail: `project_disk_full_incident_2026_08_13` memory
