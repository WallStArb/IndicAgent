# Buying pre-2016 US equity intraday history: vendor memo - Idea

**Status:** Decided. Owner approved the Massive purchase 2026-11-07 (reversing the 2026-11-04 decline); execution is todo 600. This memo keeps the reasoning and the admission checks.
**Author:** Claude (Opus 5.5), session ab, 2026-11-04.
**Informed by:** measured IBKR throughput (todo 534; `ohlcv_request`, 2026-10-28 to 11-03),
`docs/foundation/canonical-truth-registry.md` (provider matrix, D-191-P/Q), the raw-capture law
(todo 528), `reference_databento_api_access` memory and `docs/reference/databento-api.md`.

## Why Massive

- **Same tape as our post-2016 primary.** The registry records Alpaca SIP as Polygon.io's consolidated feed (Polygon was renamed Massive on 2025-10-30). Massive's 2003 to 2015 minute aggregates should share a basis with the canonical 5m we hold from 2016-01-04: one vendor basis from 2003 to today, no 2016 seam. To be proven by the basis study, not assumed.
- **Survivorship.** Delisted tickers keep their history and the dated All Tickers endpoint lists the universe as of any date, which makes a point-in-time membership table possible. IBKR serves only contracts that trade today, so its pre-2016 history is survivors only.
- **Speed and size.** Daily S3 flat files, all symbols, minute aggregates from 2003-09-10. Measured 2026-11-08: a 2010 day file is about 13.5 MB, about 3.4 GB a year, about 80 GB compressed for everything (owner's figures from the docs: 0.6 GB in 2003, about 3 GB a year to 2021, 5 to 6 GB after). Hours to load, against IBKR's weeks (about 4 names an hour, 13.5 ms of server time per bar, history server saturates at 4 concurrent requests).
- **Rejected or second choice (vendor facts from 2026-11-04, unverified marketing):** FirstRate Data is the fallback (one-time purchase, 1m back to 2000, about 7,000 delisted names, extended hours; no dated ticker reference). Kibot (uneven delisted coverage by its own FAQ), AlgoSeek (institutional pricing) and Nasdaq Data Link (no minute archive) are out. Databento has no pre-2016 equities (EQUS.MINI starts 2023), so it is not a pre-2016 source.

## Status of the account (2026-11-08)

The S3 key (in `.env` as `MASSIVE_S3_*`) lists the bucket back to 2003 but every download returns 403: the free plan lists only. The purchase of a plan with full history is still needed (Advanced per Massive's docs; flat files are said to be included in paid plans).

## What admission needs (raw-capture law, todo 528)

- One `history_leaf` (a flat-file reader) writing `ohlcv_raw` under a new `(vendor, kind)`, raw and last-wins; one `VendorIngress` row; APR seeds. 5m is aggregated from 1m in the leaf as a pure function; traded minutes only, no fills.
- A measured basis study before any policy row names it, pilot first (one year, 2010, plus 2016 overlap days):
  - 2016 onward against `(alpaca, sip_rth)`: expect near-identity; measure close agreement, volume ratio and per-session bar count.
  - 2006 to 2015 against IBKR `named` 5m: close agreement; volume basis (IBKR measured 0.38 to 0.95 of SIP).
  - Its own 1d aggregation against canonical 1d; split handling against the corporate-action table.
  - Check the `window_start` unit (the docs disagree on seconds versus nanoseconds), fractional share volume in files after 2026-02-23, and that known delisted tickers appear in a 2010 file.
- Survivorship needs a universe change beyond the vendor: delisted names have no `instruments` rows and the onboarding SOP never onboards a dead name. Open design item: point-in-time membership (todo 491's `universe_entry_date` gains an exit date), a delisting return convention, and the research runner reading membership as of t. Without it the bought data only deepens the survivors. Owner 2026-11-07: keep all data; research scope comes from point-in-time rules.

Sources (fetched 2026-11-04 and 2026-11-07): [Massive minute aggregates](https://massive.com/docs/flat-files/stocks/minute-aggregates), [Massive All Tickers](https://massive.com/docs/rest/stocks/tickers/all-tickers), [FirstRate stocks complete](https://firstratedata.com/b/22/stock-complete-historical-intraday).
