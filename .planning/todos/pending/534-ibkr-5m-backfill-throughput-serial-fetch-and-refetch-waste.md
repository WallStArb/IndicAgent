---
status: pending
priority: P0
filed: 2026-10-12
source: 5m backfill throughput check, 2026-10-12 (ohlcv_request, fetcher log)
owner: phase 189 fetcher
---

# The 5m backfill runs about 2 symbols an hour; serial fetch and refetch waste are the cause

## What

Measured 2026-10-12 from `ohlcv_request` (ibkr, 5m, last 30 hours). A full-depth 5m symbol takes
about 49 requests (7,300 depth days over 150-day chunks), and a symbol's requests total 91 across
runs (HON, IGV, IHF, ISRG), so most symbols are fetched about twice. 5m request latency is p50
27.8 s, p90 52.4 s (1d is 0.1 s), so the gateway is healthy and 5m ranges are just slow. The fetch
loop (`ohlcv_history_fetcher.py` `_loop`) takes one item at a time with one request in flight, so
throughput is bound by latency (about 130 requests an hour), not by the pacing limiter
(`infra.ibkr.rate_limit_max_requests` 58 per 600 s, 348 an hour). Result: 33 minutes a symbol, about
1.8 symbols an hour, about 35 days for 1,529 names.

## Two causes

1. Refetch waste. A chunk that overlaps a mix of own-vendor and Alpaca rows is refused when the
   changed ratio (counted over all overlapped rows, so cross-vendor differences included) exceeds
   2%. `_authored_by_other_vendor` only excuses an all-other-vendor overlap, so the mixed chunk
   lands in `refusals`, the item fails and is queued again. HON: changed 527 (exactly its Alpaca
   rows) of 11,657. No interim fix (decided 2026-10-12): the refusal is also what stops an IBKR
   chunk from overwriting Alpaca rows through the full-row upsert in
   `services/ohlcv_ingress_contract.py`, so a same-vendor ratio alone would silently overwrite
   them, and a safe version (partition other-vendor rows out of the grid write) is throwaway work
   because 533 replaces the guard with a per-vendor raw table. Refetch waste is removed by 533.
2. Serial fetch (do first; independent of 533). Keep several requests in flight (worker pool over items, shared sliding-window
   limiter, one DB connection per item, outcomes recorded serially in main). At 28 s latency, 3 to
   4 in flight reaches the 348 an hour limiter ceiling, about 7 symbols an hour once refetch is gone.
   The concurrency count is an APR key (`infra.ibkr.history_concurrency`). 505 measures the real
   pacing ceiling and should run first or alongside.

## Acceptance

5m symbols an hour measured from `ohlcv_request` before and after, refusals per symbol near zero for
names with an Alpaca tail, `repro_frozen` untouched (no research code edited).

## Progress

2026-10-12: concurrency landed (985911234, migration 471 applied live). `_loop` runs one worker per
context, `infra.backfill.fetch_concurrency` (seeded 1, set to 2 for the next run). The live run
that started 21:25 EDT keeps its old code and serial loop until its 240 minute budget ends; the
next timer fire picks up the new code. Raise to 3-4 after one clean run. Open risk: a stall in one
worker reconnects the shared provider (`_reconnect`) while the others have requests in flight;
their retries absorb it, but watch `gateway_lost` and `hist_pacing_error` counts on the first runs.
Alpaca depth floor re-probed 2026-10-12: requests from 2010 to 2015 return a first bar at
2016-01-01, so IBKR is the only 5m source for 2006-2015.

## Update 2026-10-13

The timeout fix (fd1bfba4a) removed the 375 s stalls: 0 failed requests since 04:45 EDT, 0.9 to
1.0M bars an hour against 0.5 to 0.7M. Cause 1 is settled by owner direction: raw is stored per
source, agnostic to every other source, and a source's gap is its expected slots minus its own raw
slots minus its own answered windows. Plan 191-04 deletes the cross-vendor refusal; the fetcher's
gap planner (`_plan_gaps`, overlap and refetch lanes) moves to the per-source rule in the plan that
cuts the fetcher over to `ohlcv_raw`. Do not restrict the queue to pre-2016: post-2016 IBKR chunks
are IBKR raw we want. Cause 2 (serial fetch, bounded concurrency) is unchanged and still first.

## Status 2026-10-28 (indicagent-5b, owner prompt)

Owner expected the pre-2016 5m for names missing it done by now. Measured (read-only): 1,279
active names listed before 2016; 43 have IBKR 5m to their start, 217 partial, 1,019 none; about
9,200 name-years remain. The fetcher timer re-fires 15 min after each run, so the lane is near
continuous, but 5m throughput is 76 to 88 requests an hour: median answer latency 73 s (the
pilot saw 28 s) times 2 workers. Concurrency is the lever: `infra.backfill.fetch_concurrency`
set 2 to 4 on 2026-10-28 13:54Z (config version 3; migration 531 corrected the key's value type,
which had blocked ConfigService.set). Read the next run's request rate (expect about 175/h) and
pacing errors; revert to 2 if pacing errors or gateway drops appear. Idle time between runs is
about 45 min (post-fetch stages, then the 15 min timer). Remaining decisions for 3a: ETA, name
order (feature-family names first), shortening the post-fetch gap. Todo 556 covers ten other
config rows whose value types the validator rejects.
