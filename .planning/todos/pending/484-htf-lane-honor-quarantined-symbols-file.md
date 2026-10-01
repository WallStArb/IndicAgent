---
status: pending
priority: P3
filed: 2026-10-01
source: interactive session, 2026-10-01 reboot recovery (HOOD quarantine)
---

# HTF backfill lane should subtract a quarantine file from its symbol list

## What

A name whose IBKR requests hang or fail every attempt (HOOD on 2026-10-01: head probe
Error 162, then every data request a 60s timeout; conId 504546674) costs the lane its
window-retry budget per attempt: ~6 min per failed window, ~18 min for both timeframes,
on every one of the lane's up-to-50 attempts for as long as the name stays poisoned
(~15 h worst case across a campaign). The pipeline itself moves past failed names
(`ibkr.hist_chunk_failed_all_retries` records the skip and the walk continues, D-05), so
nothing stalls indefinitely - but the retry tax repeats per attempt because the name
stays in the list and the completion check (`skipped (` lines) keeps every attempt
"unclean".

The 2026-10-01 workaround was manual and blunt: kill the lane stack, `sed` HOOD out of
the git-tracked `logs/backfill_ops/intraday_htf/all.symbols`, note the reason in a new
`quarantined.symbols`, relaunch (commit `d57b4a376`). Editing the canonical list to
work around one bad name is the wrong direction: the list is campaign state, the
quarantine is operational state.

## Change

`logs/backfill_ops/intraday_htf_lane.sh` (and `intraday_5m_lane.sh` for symmetry):
after reading the symbols CSV, subtract any name listed in
`logs/backfill_ops/intraday_htf/quarantined.symbols` (one symbol per line, `#`
comments) if that file exists. Two lines of shell. `all.symbols` stays canonical and
untouched; quarantining a name becomes appending one line, effective on the next
attempt, no kill required.

Constraints: never edit a lane script while its loop runs (bash reads scripts
incrementally) - land this at the next cutover stop alongside todo 452's deferred
lane-script convergence (shared skeleton factoring, wrappers' permanent home). A
pipeline-side circuit breaker (per-name consecutive-failure counter persisted across
attempts) is the fuller fix but is not worth building given 185-18/186 will replace
this walk; the file is enough until then.

## Related

- Todo 452 (lane script convergence, the cutover stop this lands at).
- Todo 449 (the campaign this serves); 185-18 task 1a removes the per-attempt rescan
  tax that multiplies the cost of a poisoned name (fewer attempts, less retry burn).
- Memory: `project_intraday_backfill_todo449` (2026-10-01 entry) has the full incident.
