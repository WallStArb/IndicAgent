---
status: pending
priority: P2
filed: 2026-09-27
source: session 2026-09-27 (todo 449 HTF lane monitoring): measured the rate cap as non-binding for heavy TFs; the parallel-lane "one stream" finding was a confounded test
---

# IBKR backfill throughput: concurrency probe, then pipelined persistence

## What

Big IBKR backfills are wall-clock bound by the serial walk loop in
`src/providers/ibkr.py::_walk_history` (limiter acquire -> request -> parse -> await `on_chunk`
persistence -> next request), not by our configured limits. Measured 2026-09-27 while 449's HTF
lane ran: ~102 requests/hour actual against the 348/hour the shared 58-per-10-min cap allows
(3.4x headroom; the limiter never engages for heavy timeframes), ~30 s per heavy chunk
end-to-end, and py-spy shows the main thread idle in the event-loop `select` (pure network
wait). Chunk durations already sit at the empirically probed per-request ceilings
(`production/migrations/302_ibkr_chunk_days_and_rate_limit_recalibration.sql`,
`303_ibkr_chunk_days_15m_year_rounding_fix.sql`; 1h 20-yr single-shot tested and failed), so
per-name request count is fixed by depth. Rate and chunk size are therefore non-levers.

Two levers remain, in order:

1. **Concurrency probe (do first, decides everything).** The 449 finding "IBKR serves one heavy
   history stream at a time" (2026-09-27: 4 parallel 5m lanes, one progressed while the others
   timed out) came from 4 separate processes with 4 connections and 4 independent rate
   limiters - confounded, not a clean measurement of HMDS request serialization. Run a
   controlled probe: one process, one connection (own client ID <= 50, e.g. 47), 2-4
   outstanding `reqHistoricalDataAsync` calls on heavy windows (15m/730d, 5m/150d), against
   the same requests issued serially as control; compare aggregate bars/min. Build it from the
   existing probe pattern
   (`scripts/infrastructure/backfill/infrastructure_ibkr_chunk_and_rate_limit_probe.py`,
   which already has `--rate-ceilings` for the rate dimension).
2. **Act on the outcome.**
   - If concurrency degrades/serializes server-side: pipeline the walk instead - issue the next
     chunk request immediately and persist the previous chunk concurrently (bounded queue, one
     persister task; idempotent `ON CONFLICT DO NOTHING` upserts make chunk order irrelevant,
     and `ibkr.py` stays DB-ignorant via the existing `on_chunk` callback). Bounded win,
     roughly the local share (~10-25%).
   - If concurrency holds: bounded concurrent requests in the walk - the bigger win, roughly
     linear in the concurrency that survives.
   Record the result with migration-302-style provenance (a migration or APR description
   update), not just a log line.

## Constraints

- Never run the probe while 449's chain is fetching (it would corrupt both the measurement and
  the lane); use a quiet window - the HTF->5m cutover, or after the campaign completes
  (~mid-Oct 2026). Check `pgrep -af infrastructure_run_historical_pipeline.py` first.
- Do not raise `infra.ibkr.rate_limit_max_requests` expecting throughput: measured non-binding
  for heavy TFs (it binds only cheap-request regimes like 1d sweeps, which already have the
  200 by-tf override).
- Do not push `infra.ibkr.chunk_days.*` beyond the probed ceilings without new evidence.
- Client IDs must stay <= `_MAX_CLIENT_ID=50` in `src/providers/ibkr.py`.

## References

- Todo 449 (the campaign and the confounded parallel-lane measurement), todo 452 deferred
  (end-of-campaign backfill tooling convergence - natural home for any lane-script changes).
- `src/providers/CLAUDE.md` chunk table and rate-limit notes.
- Session evidence 2026-09-27: request-cadence arithmetic from
  `logs/backfill_ops/intraday_htf/htf_all_attempt1.log`, py-spy dump of the lane process.
