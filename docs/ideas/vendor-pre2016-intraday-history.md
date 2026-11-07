# Buying pre-2016 US equity intraday history: vendor memo - Idea

**Status:** Idea, 2026-11-04; Massive purchase approved by the owner 2026-11-07 (todo 600). A decision memo for the owner, filed by the todo 534 lane at the lead's
request (indicagent-16). Nothing purchased, no signups. Vendor facts come from the vendors' own pages
on 2026-11-04 and are marked "unverified" where only marketing copy or a third party says so.
**Author:** Claude (Opus 5.5), session ab, 2026-11-04.
**Informed by:** measured IBKR throughput (todo 534; `ohlcv_request`, 2026-10-28 to 11-03),
`docs/foundation/canonical-truth-registry.md` (provider matrix, D-191-P/Q), the raw-capture law
(todo 528), `reference_databento_api_access` memory and `docs/reference/databento-api.md`.

## Why buy

IBKR is a brokerage feed doing a history vendor's job. Measured 2026-11-03: it answers 5m at a fixed
~13.5 ms per bar whatever the window size or era, and its history server saturates at about 4
concurrent requests (8 workers collapsed throughput to ~132k bars/h, 4 give ~1.1M). With pre-2016
windows first (defer_after, fabb62e5a), the ceiling is about 4 names an hour; 824 of the 1,279 names
listed before 2016 have no IBKR 5m before 2016, so roughly 9 days of clean running, more with
gateway drops. Two limits no fetch speed fixes:

1. **Survivorship.** IBKR serves history only for contracts that trade today. A 2006-2015 intraday
   corpus from IBKR is today's survivors only, so every cross-sectional test on it carries
   survivorship bias. This is the primary criterion, above speed.
2. **Entity continuity.** Vendors key history by ticker. Ticker reuse puts a predecessor's prices
   under today's symbol (566 class 3a: AKTS, CART, EXE, DOW and others). A vendor with dated,
   point-in-time ticker reference data lets us join by entity, not by string.

Extended hours (04:00-20:00 ET) are a secondary question. Canonical 5m is RTH-only by design
(bar_selection takes `sip_rth` on the regular-hours grid; features and `panel.forward_returns` read
RTH), so extended-hours bars have no consumer until the owner changes the session definition. The
lead ruled no IBKR extended-hours fetch (2026-11-04). A bought source that carries them costs nothing
extra, so they are scored but not required.

## Candidates

| Vendor | Pre-2016 depth | Delisted names | Point-in-time tickers | Extended hours | Adjustment | Price | Verdict |
|---|---|---|---|---|---|---|---|
| Massive (Polygon.io) | 2003-09-10, minute aggregates as daily S3 flat files | Yes, history kept as published, tickers marked inactive | Yes: All Tickers queried by date | Yes, in aggregates (unverified for 2003-2010) | Raw prints; splits from the reference API | Advanced plan $199/mo lists "all history" (third parties say lower plans cap at 5-10 years; unverified) | **Recommended** |
| FirstRate Data | Jan 2000, 1m/5m/30m/1h | ~7,000 delisted of 16,322 (the R3000 product has only 200) | Ticker lists; no dated reference found | Yes, pre and post market | Unadjusted (1m and 1d only), split, split+dividend | One-time purchase, not listed on the pages read | Strong second |
| Kibot | 1998, 1m and 5m | Included, but by its own FAQ uneven: thin and short-lived tickers often missing; index packages "not survivorship-bias-free" | Weekly listed/delisted symbol lists | Not stated | Not checked | All-stocks 1m $3,000 one-time | Weak on survivorship |
| AlgoSeek | 2007 (SIP/TAQ) | Yes, every listed US equity since 2007 | Security master in the package (unverified) | Yes, 04:00-20:00 plus FINRA TRF | Raw and adjusted products | Institutional; one extended minute bar product listed at $900, no full schedule | Best data, opaque price |
| Databento | 2018 at the earliest (EQUS.MINI from 2023-03-28) | n/a | Yes | Yes | n/a | Usage-based | **Out**: no pre-2016 equities |
| Nasdaq Data Link | No documented minute archive | Not documented | n/a | n/a | n/a | n/a | **Out** |

## Recommendation: Massive, one month of the plan that unlocks full history

1. **Same tape as our post-2016 primary.** The registry records Alpaca SIP as Polygon.io's
   consolidated feed (Polygon was renamed Massive on 2025-10-30). Massive's 2003-2015 minute
   aggregates therefore share a basis with the canonical 5m we already hold after 2016-01-04: one
   vendor basis from 2003 to today, with no 2016 seam to adjust for. That is the cleanest form of
   the data-quality principle, and none of the other candidates offers it.
2. **Survivorship.** Delisted tickers keep their history, and the dated All Tickers endpoint gives
   the listed universe as of any date, which makes a point-in-time membership table possible.
3. **Cost and speed.** Buy one month, bulk-download the flat files (about 5,800 trading-day files
   from 2003; a rough guess is 0.3-0.6 TB compressed against 312 GB free, so measure one year
   first and plan storage), then cancel. Load time is hours, not IBKR's weeks.
4. **Fallback.** If Massive's history behind the paywall or its early-year extended-hours coverage
   disappoints, FirstRate Data is the second choice: a one-time purchase with unadjusted 1m, 7,000
   delisted names and extended hours. Its gaps: no dated ticker reference, and zero-volume minutes
   are dropped, which our no-fill law tolerates (missing is NaN, never a placeholder).

## What admission needs (raw-capture law, todo 528)

- One `history_leaf` (a flat-file reader, not a REST pager) writing `ohlcv_raw` under a new
  `(vendor, kind)`, raw and last-wins; one `VendorIngress` row; APR seeds for its knobs. 5m is
  aggregated from 1m in the leaf, the way Databento's guidance expects, as a pure function.
- A measured basis study before any policy row names it:
  - 2016-2026 overlap against `(alpaca, sip_rth)`: expect near-identity (same tape); measure close
    agreement, volume ratio and the bar-count match per session.
  - 2006-2015 overlap against IBKR `named` 5m: close agreement; volume basis (IBKR measured 0.38-0.95
    of SIP, so the ratio is expected below 1).
  - Its own 1d aggregation against canonical 1d; split handling against the corporate-action table.
- Survivorship needs a universe change beyond the vendor. Delisted names have no `instruments` rows
  today, and the onboarding SOP never onboards a dead name. Admitting them is an owner design
  decision: point-in-time membership (todo 491's `universe_entry_date` gains an exit date), a
  delisting return convention, and the research runner reading membership as of t. Without it, the
  bought data only deepens the survivors.

## Decisions for the owner

1. Approve one month of Massive's full-history plan (or FirstRate as the one-time alternative).
2. Approve a pilot first: one year (2010) of flat files, the basis study on it, then the rest.
3. Decide whether delisted names enter the research universe (the survivorship fix), which opens
   its own design item.

Sources (fetched 2026-11-04): [Massive minute aggregates](https://massive.com/docs/flat-files/stocks/minute-aggregates),
[Massive history depth](https://massive.com/knowledge-base/article/how-much-historical-stock-data-does-massive-have),
[Massive stocks](https://massive.com/stocks), [Massive All Tickers](https://massive.com/docs/rest/stocks/tickers/all-tickers),
[FirstRate dataset card](https://firstratedata.com/ai/datasets/us-stocks-intraday),
[FirstRate stocks complete](https://firstratedata.com/b/22/stock-complete-historical-intraday),
[Kibot all stocks 1m](https://www.kibot.com/historical-data/all-stocks-1-minute-intraday-data.html),
[Kibot FAQ](https://www.kibot.com/faq.html), [AlgoSeek equities](https://algoseek.com/equity/),
[AlgoSeek minute bar guide](https://us-equity-market-data-docs.s3.amazonaws.com/algoseek.US.EquityTrades.Only.Minute.Bars.pdf),
[Databento EQUS.MINI](https://databento.com/docs/venues-and-datasets/equs-mini),
[Databento stocks](https://databento.com/stocks), [Nasdaq Data Link CQT](https://data.nasdaq.com/databases/CQT).
