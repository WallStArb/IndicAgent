# 296 - client-44 backfill: connection-drop gaps need a follow-up pass

**Filed:** 2026-08-10
**Source:** Live monitoring of client-44's 43-symbol expansion-cohort backfill, this session
**Status:** pending, not blocking (main run continues; this is a cleanup pass for after)

## What

While monitoring `logs/backfill_client44_20260810.log`, found the DB connection dropping
mid-fetch on 4 symbols so far (13 processed at time of writing): PGR, AA, UNP, AVGO. Each
lost its `5m` and/or `1m` and/or `15m` fetch partway through when a slow checkpoint
(`docker logs timescaledb` shows one taking 251s vs. the normal <1s, competing for I/O with
the backfill's heavy compressed-chunk writes) stalled a client INSERT for ~16 minutes until
the Python client gave up and closed the connection. The pipeline's own reconnect logic
recovers cleanly and moves on to the next symbol, but never goes back to finish what that
dead connection was mid-fetching -- so the timeframe is left silently short.

Confirmed gaps as of 2026-08-10 21:00 UTC:

| Symbol | Missing |
|---|---|
| PGR | 5m (stops 2026-08-07 19:55), 1m entirely missing |
| AA | 15m (stops 2026-08-07 19:45), 5m entirely missing, 1m entirely missing |
| UNP | 5m (stops 2026-08-07 19:55), 1m entirely missing |
| AVGO | 5m (stops 2026-08-07 19:55), 1m entirely missing |

**Update 2026-08-11 00:49 UTC:** HD also hit this (20 symbols processed by this point, 5/20 =
25% hit rate). Exact gap not yet spot-checked in DB -- re-run the completeness query for HD
before the fix, same pattern as the others (`SELECT timeframe, count(*), max(timestamp) FROM
market_data_ohlcv WHERE symbol='HD' GROUP BY timeframe`).

**Update 2026-08-11 10:03 UTC:** T also hit this (24/43 symbols processed, 6/24 = 25% hit rate,
holding steady with prior samples). Still running, now on VRTX (25th symbol). Exact gap not yet
spot-checked for T -- same completeness query pattern as HD above.

At ~25-31% of symbols hit so far, expect several more by the time client-44 finishes all 43
symbols -- re-grep the log for the final count before running the fix, don't rely on this
list being complete.

## Fix

`detect_gaps()` is idempotent (only fetches what's missing), so a small follow-up run scoped
to just the affected symbols will cleanly fill exactly these gaps without redoing anything
already present:

```
.venv/bin/python -u scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py \
  --client-id 45 --symbols PGR,AA,UNP,AVGO,<any more found by final grep>
```

**Do NOT run this while client-44 is still active.** Each process tracks IBKR's 55-req/600s
pacing limit independently in-memory (`_hist_rate_limiter` in `src/providers/ibkr.py`) --
running two processes concurrently means neither knows about the other's request budget, and
combined they could exceed IBKR's real 60-req/10min server-side cap (Error 162). Wait for
client-44 to finish, or at minimum confirm it's idle between symbols before this runs.

## Where

- `grep -B3 "connection is closed\|DB connection lost\|connection to client lost" logs/backfill_client44_20260810.log`
  to get the full final list of affected symbols once client-44 completes.
- `docker logs timescaledb --since ... | grep -i checkpoint` to confirm the checkpoint-vs-write
  contention theory if it recurs -- not yet root-caused beyond "correlated in time", could be
  worth tuning `max_wal_size` up from its current 1GB if this keeps happening on future backfills.
