---
status: pending
priority: P0
filed: 2026-09-26
source: 2026-09-26 universe expansion 1d backfill
---

# IBKR daily history starts at a name's last primary-listing venue change

## What

The 2026-09-26 1d backfill (20-year single-shot request per symbol, `_MAX_CHUNK_DAYS["1d"]`
= 7300) returned history that starts years after the security began trading, for names
whose primary listing moved:

| Symbol | First 1d bar | Known listing move |
|---|---|---|
| UAL | 2018-09-10 | NYSE to Nasdaq, 2018 |
| COO | 2023-09-26 | NYSE to Nasdaq, 2023 |
| IEI | 2017-08-03 | iShares bond ETFs moved listing venue around 2017 |
| RSPR | 2018-04-09 | renamed from EWRE in 2023 (fund older than 2018) |
| CRH | 2023-09-25 | ordinary shares replaced the NYSE ADR, 2023 |

Checked on the first 87 names backfilled; re-run the check once the backfill finishes
(first 1d bar after 2016 against the name's known trading history).

## Why it matters

- The research panel treats these names as late listings, so they drop out of every
  window before the move. This is coverage loss, not wrong prices.
- The 2026-09-26 history screen (since deleted) failed such names as having no history,
  which biased the small-cap draws against names that changed venue (todo 434).
- Unknown how many of the 273 older names have the same gap.

## Probe results (2026-09-26)

The history exists. It is a routing limit of IBKR's history service, not missing data:

- SMART-routed TRADES requests serve history only from the current primary listing. A
  2-year window before the move returns "HMDS query returned no data" for UAL (2015-16),
  ADI (2009-10) and XEL (2014-15), with the same conId throughout (ADI is conId 4157).
  Pinning `primaryExchange=NYSE` on a SMART contract does not help; ADJUSTED_LAST has the
  same floor.
- The same contract routed to the old venue (`Stock(sym, "NYSE", "USD")`) returns the full
  window: 504 daily bars for ADI 2009-10 and for UAL 2015-16.
- Venue-routed bars count that venue's trades only. JPM, June 2025, SMART vs NYSE: closes
  identical (the primary's closing auction is the official close), NYSE volume 38-54% of
  consolidated, varying daily. Opens should match for the same reason; highs and lows can be
  slightly narrower.
- A full-depth 1d request on a moved name returns the post-move span plus Error 162 "Query
  failed". The backfill log's "Query failed" lines are a first-pass inventory of moved names
  (2026-09-26 run: ADP, ADI, XEL, UAL, IEI, CAR, plus CHTR and MATX, which are genuine
  late listings).

## The empty-history check recorded these gaps as fact

`ohlcv_empty_history` (migrations 354/355, shipped 2026-09-24) holds 18 1d rows whose empty
range ends after 2008, written 2026-09-25 with `n_confirming_chunks = 2`. Most match
known venue moves: AMD to 2014-12-31, CSX to 2015-12-21, PEP to 2017-12-19, MAR to
2013-10-18, SLM to 2011-12-09, TLT to 2016-02-02, IEF/SHY/PFF to 2017-08-02, MCHI to
2016-02-03. Others are genuine late listings (GEV) and need no change. The nightly backfill
now skips these ranges, so they are never retried. The same holds for 72 of the 88 rows per
intraday timeframe, though intraday depth is also capped by IBKR's own limits.

The check cannot tell "nothing traded" from "nothing on this route": a SMART request
returning no data twice is not verification. The 2026-09-26 backfill of the 546 new names
will add rows the same way (ADI, ADP, XEL, UAL, IEI, CAR at least).

## Intraday is truncated too

5m and 1h history for the moved names starts on exactly the same dates as their 1d history:
AMD 2015-01-02, CSX 2015-12-22, IEF 2017-08-03, PEP 2017-12-20, TLT 2016-02-03. The intraday
corpus, and every `feature_vectors` row built from it, treats these names as listed at their
move. 72 of the 88 `ohlcv_empty_history` rows per intraday timeframe are likely the same false
record.

## Decisions (owner, 2026-09-26)

- Re-tiered P0.
- Volume: former-venue bars keep their venue volume in storage, and
  `market_data_ohlcv_tradeable` reports it as NULL (migration 374).
- Ship the empty-history rule now in verify-only mode: former venues are asked, history found
  there blocks the empty record and is logged, and no venue bar is stored until the
  listing-venue validation study passes (`infra.ibkr.venue_fallback.store_bars` = false).
- The full fix is part of the daily data foundation phase
  (`docs/plans/2026-09-26-daily-data-foundation.md`, D3 and D4).

## Status

Verify-only fix merged 2026-09-26 (0d225b312): former-venue recovery that logs
(`ibkr.hist_venue_fallback_recovered`) and stores nothing (`infra.ibkr.venue_fallback.store_bars`
false), automatic `fetch_complete`, per-timeframe rate limit (`{"1d": 200}`). Migrations 374
(tradeable view NULLs venue volume; 1d `ohlcv_empty_history` rows deleted for re-verification)
and 375 applied. IBKR accepts the ISLAND, ARCA, NYSE, AMEX and BATS routing codes.

## Next

1. Re-run the 1d backfill for every active name once the 113-name backfill is promoted. Its
   `ibkr.hist_venue_fallback_recovered` and "Query failed" lines are the moved-name inventory
   (D6), and it re-verifies 1d empty history under the new rule.
2. D3 validation study: on at least 30 names whose listing venue is known today (NYSE, Nasdaq,
   NYSE Arca), check that the listing venue has the most volume and that only its closes match
   SMART's. Pass: set `store_bars` true and re-backfill the moved names; check closes chain
   across each move date. Fail: venue bars stay unstored.
3. Intraday: extend verify-only to intraday timeframes (72 of 88 empty-history rows per
   timeframe), then recovery after the study covers intraday bars, through a planned corpus
   recompute (never under a live ic_engine run).
4. Check the September finding that the head-timestamp lookup failed with "Query failed" for
   112 of 273 active names: likely the same mechanism.
