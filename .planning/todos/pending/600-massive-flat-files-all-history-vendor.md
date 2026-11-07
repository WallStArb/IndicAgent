---
status: pending
priority: P1
filed: 2026-11-07
source: owner ruling 2026-11-07 (reverses the 2026-11-04 decision not to buy pre-2016 history)
---

# Onboard Massive flat files as a vendor: all symbols, all history

## What

Owner 2026-11-07: "no reason not to have it and use it". Buy the Massive Stocks Advanced plan for one month, download every minute-aggregate flat file (`us_stocks_sip/minute_aggs_v1`, 2003 to present, all symbols, about 80 GB compressed, unadjusted consolidated SIP), and keep all of it. This removes the survivorship caveat for pre-2016 5m and replaces the IBKR bottleneck (about 4 names an hour).

Docs: https://massive.com/docs/flat-files/stocks/minute-aggregates (S3-compatible `files.massive.com`, bucket `flatfiles`, separate S3 key and secret from the dashboard; the `MASSIVE_API_KEY` in `.env` is a free plan and does not open these).

## Plan

1. Owner buys the plan and supplies the S3 key and secret through `.env`. Confirm file layout, size per file and the `window_start` unit (the docs disagree on seconds versus nanoseconds) from a real listing.
2. Basis study before admission: about 5 days across different years for about 30 names, against IBKR and Alpaca SIP. The 2016 seam matters most.
3. Archive the raw files unmodified (permanent raw).
4. Onboard as a vendor per the capture law (528): one `history_leaf`, one `VendorIngress` row, APR seeds. Aggregate 1m to 5m with traded bars only and no fills; load all symbols into `ohlcv_raw` under the new vendor. Load 1m only if a hypothesis needs it, after measuring compressed size on one month.
5. Ticker to instrument mapping for renamed, reused and delisted symbols, point in time. Research scope still comes from point-in-time universe rules under the onboarding SOP, never from screening on history or returns.
6. Update `bar_source_policy` so pre-2016 5m selects Massive; IBKR stays as fallback. The survivorship caveat lifts only for spans where Massive is selected.

## Constraints

No corpus compute until the data is complete (2026-11-04 ruling); the IBKR backfill keeps running until Massive is admitted. Disk: 715 GB free, database 79 GB (checked 2026-11-07).
