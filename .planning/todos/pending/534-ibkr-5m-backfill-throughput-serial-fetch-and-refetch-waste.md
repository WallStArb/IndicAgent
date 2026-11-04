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

## History (summary of the 2026-10-12 to 2026-10-31 notes)

- Concurrency landed 2026-10-12 (`infra.backfill.fetch_concurrency`, migration 471); the timeout fix
  (fd1bfba4a) removed the 375 s stalls. Throughput: 0.9 to 1.0M bars/h on 2026-10-13, about 0.65M/h
  on 2026-10-31 under the stage-2 rebuild's host load, about 0.7M/h on 2026-11-02 (see below).
- Alpaca's 5m depth floor is 2016-01-01, so IBKR is the only 5m source for 2006-2015.
- Raw is stored per source, agnostic to every other source (owner direction); a source's gap is its
  expected slots minus its own raw slots minus its own answered windows. Do not restrict the queue to
  pre-2016: post-2016 IBKR chunks are IBKR raw we want.
- Coverage 2026-10-31: 1,175 of the active names listed before 2016 had no pre-2016 IBKR 5m, 354 had
  some; about 9,200 name-years remain at about 19.7k bars per name-year (about 181M bars).
- Name order (PM decision 2026-10-31, owner can override): names with none before deepening
  partials; among none-names, feature-family and regime-kernel names first. The 2006 target for the
  deepest names comes after every name has any pre-2016 coverage.

## Status 2026-11-02: fetch_concurrency 4 (owner decision)

Setting: `infra.backfill.fetch_concurrency` = 4 (config_history version 6), outer timeout 240 s
(`infra.ibkr.historical_request_timeout_sec`). Failure modes and their fixes: `docs/reference/gotchas.md`
("IBKR history fetcher: how a run stops taking in data").

Measured (ohlcv_raw ibkr 5m rows per hour): 8 lanes peaked at 131,958 rows/h and logged 62 outer
timeouts in 45 minutes before ending `stalled`; 3 lanes ran 2 h 47 min at about 713,000 rows/h with
0 outer timeouts and no slowdown at the US open; 4 lanes ran about 715,000 to 737,000 rows/h over
the first 33 minutes, so no gain over 3 and no loss. The owner chose to keep 4 and stop testing
concurrency. Throughput appears limited below 12 lanes by something other than lane count (IBKR
pacing or per-request latency at the gateway); not investigated.

## Status 2026-11-04: pre-2016 first (session ab)

`infra.backfill.defer_after` (migration 563, fabb62e5a) is the planning horizon: IBKR 5m gaps after
it are deferred (status `deferred`, never recorded, never counted as intake); escalations ignore it.
In the 3 hours before the 2026-11-03 23:19Z restart, 0% of IBKR 5m asks were pre-2016; after it,
100%. Measured throughput: about 13.5 ms of server time per bar, flat across window size and era; 4
lanes give about 1.1M rows/h (8 collapsed to about 132k); the 5m chunk ceiling is 150 days; pacing
cap 58 requests per 10 minutes. Coalescing small gap asks is not material (1.9% of server time;
`gap_cluster_max_days` 90 already merges near holes). No IBKR extended-hours fetch (lead ruling).

Buying the pre-2016 history instead: `docs/ideas/vendor-pre2016-intraday-history.md` (Massive
recommended, FirstRate second), waiting on the owner.

## Owner decision 2026-11-04: IBKR only, survivorship bias accepted

The owner declined buying pre-2016 intraday history (Massive and FirstRate, vendor memo). IBKR stays
the only pre-2016 5m source, and its completion is the data gate for the corpus rerun (todo 584
decision 1). IBKR serves only names that trade today and the universe was chosen today, so every
result whose sample includes pre-2016 5m carries a survivorship caveat in its record and summary
card. Coverage at the decision (lead, from `ohlcv_raw` against each name's 1d start): of 1,177
names with 1d before 2016, 84 at depth, 410 partial, 683 none. Fetcher healthy at about 1M bars/h
after the 2026-11-04 11:45 EST gateway restart race (one failed start, recovered on the 12:00 timer).
