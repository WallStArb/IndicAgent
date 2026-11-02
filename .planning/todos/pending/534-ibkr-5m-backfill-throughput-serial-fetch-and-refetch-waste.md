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

## Status 2026-10-31 22:05Z (PM, indicagent-9f): ETA and name-order decision

Measured tonight under 186-26 stage-2 load: 56.95M pre-2016 5m raw rows over 354 names touched,
adding about 336k rows in 31 minutes, so about 0.65M bars/hour (down from the 0.9-1.0M of
2026-10-13; concurrency 4 is set, the rebuild's host load is the difference, and the three
fetcher wedges today each cost a run plus about 15 minutes). Coverage: 1,175 active names still
have no pre-2016 IBKR 5m at all; 354 have some.

ETA at tonight's rate: about 9,200 remaining name-years at about 19.7k bars/name-year is about
181M bars, or roughly 11.6 days of continuous fetching at 0.65M/h; with budget gaps and wedge
recoveries, plan on about two weeks. The 538 fix (watchdog and request timeout) recovers most of
the wedge cost; approving its APR bounds is the throughput lever available now.

Name-order decision (PM; owner can override): none-names before deepening partials, so the
cross-sectional panel reaches every symbol's vendor floor before any name gets extra depth
(history depth beats freshness does not mean some names get 2006 while others still have nothing);
among none-names, feature-family and regime-kernel names go first so the 184/186 consumers
unblock earliest. The 2006 target for the deepest names is second-priority behind every name
having pre-2016 coverage at all.

## Status 2026-11-02 (indicagent-82): fetch_concurrency 3 test

Failure modes and the fixes that landed: see `docs/reference/gotchas.md` ("IBKR history fetcher:
how a run stops taking in data"): history probe (`1ebcfc9e4`, migration 554), intake watchdog
(`857b163e0`, migration 556).

Baseline, concurrency 8, outer timeout 240 s (`infra.ibkr.historical_request_timeout_sec`, set
2026-10-13; the 90 s module constant is overlaid by APR), ohlcv_raw ibkr 5m by UTC hour on
2026-11-02 (different hours from the test; the US session loads the farm from 14:30Z):

| Hour | Rows | Names |
|---|---|---|
| 04Z | 78,805 | 3 |
| 05Z | 131,958 | 4 |
| 06Z | 19,818 | 1 |
| 07Z | 27,779 | 2 |
| 08Z | 7,962 | 1 |
| 09Z | 0 | 0 |
| 10Z | 31,446 | 2 |
| 11Z | 11,628 | 1 |

The 07:45Z run (8 lanes) logged 62 outer timeouts in 45 minutes and ended `stalled` at 08:31Z.
Those timeouts happened at the 240 s timeout: 150-day chunks took over 240 s with 8 lanes against
24 to 54 s for one request alone on a quiet farm (08:41Z grid: 2 D 0.1 s, 30 D 0.2 to 12 s, 150 D
24 to 54 s), which supports a backlog reading (cancelled work still occupies the intraday queue).

Test (lead-approved): `infra.backfill.fetch_concurrency` 8 to 3 through `ConfigService.set` at
11:51:13Z (config_history version 5, changed_by `indicagent-82`), timeout left at 240 s so
concurrency is the only variable (the approval said 180 against an assumed 90 s; 180 would have
lowered the timeout). Run started 12:06:24Z (t0), window to 15:06:24Z. Decision rule, fixed
before the result: keep if the mean beats 131,958 rows/h; under 20,000 rows/h try concurrency 2
for 3 hours; between the two keep it and extend.

Interim (checked 13:41Z): 12Z hour (from 12:06:24Z) 638,680 rows over 6 names; 13Z through 13:41Z
488,099 rows over 5 names; zero outer timeouts since the run began. Final hourly numbers, the
14:30Z split and the verdict are appended here at the end of the window.

