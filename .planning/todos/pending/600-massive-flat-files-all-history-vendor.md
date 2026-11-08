---
status: pending
priority: P0
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

## Notes added 2026-11-07

- Recent files: since 2026-02-23 the SIPs report up to six decimal places for share sizes, so `volume` can be fractional in new files (our column is bigint; decide round or a separate column). From 2026-12-06 the SIPs run 23 hours a day, five days a week; canonical 5m stays RTH-only, so cut rows by session.
- Massive advertises point-in-time ticker details (2021 blog); check its reference endpoints for the ticker-reuse mapping (AKTS, CART, EXE, DOW).
- Survivorship is inferred, not stated: test that known delisted tickers appear in a 2010 file during the basis study.
- Simplify after admission (owner 2026-11-07, over-engineering concern): with whole-market daily files, completeness is "the file for each trading day exists and parses". If the basis study passes, write a deletion list covering the IBKR pre-2016 leg, the Alpaca ask-ledger readers (596 step 3) and most completeness gates; consider the same files for Alpaca-era history so one vendor and one path remain. Do not extend those systems before the study.
- Flat files are said to be included in all paid plans (Mar 2024 blog, unconfirmed); check the current plans page.

- Docs move in the same commit as the source-policy switch: the provider matrix in `docs/foundation/canonical-truth-registry.md`, the `bar_source_policy` docs, the survivorship caveat wording, and the landing copy line in `dashboard/src/lib/copy/landing.ts` ("IBKR and Alpaca bars").
- 2026-11-07/08 check: the account's S3 key (stored in `.env` as `MASSIVE_S3_*`) lists the bucket back to 2003 (a 2010 minute day file is about 13.5 MB, so about 3.4 GB a year) but every download returns 403 NOT_AUTHORIZED, minute and day aggregates, old and recent: the free plan lists only. The purchase is still needed; rerun the download check after upgrading.

## Design implications for the data layer (2026-11-08, decide after the pilot)

1. Entity identity is the one real refactor. Store Massive raw as served, keyed by ticker as of the date; add a point-in-time ticker to entity map that joins at selection, never inside raw. Delisted names need historical instrument rows with entry and exit dates (todo 491's `universe_entry_date` gains an exit date); the onboarding SOP never onboards a dead name today, so this is an owner-approved exception to write down.
2. Storage is not scope. Raw holds every symbol; research and compute scope come from a point-in-time membership table. Compute scales with scope (a 10k-name universe is roughly seven times today's), so widen in stages after the first counted test. Measure one year of raw rows before sizing the full load.
3. Completeness is a file manifest (day file exists, parses, row count, hash), not an ask ledger. Once Massive is the selected pre-2016 source, the ask-ledger readers, gap_plan for this span and most D7 completeness checks are deletion candidates.
4. Keep: the raw table design ((vendor, kind), last-wins, revision log), archive of the minute files, 5m aggregated in the leaf, 1m loaded only on demand; `bar_source_policy` names Massive for history and Alpaca nightly stays for recent days (files land about 11:00 ET the next day); raw keeps extended hours and selection cuts RTH explicitly (SIPs go 23/5 on 2026-12-06); prices stay unadjusted with splits from the corporate-action table.

## Refine our layers from what Massive shows (owner 2026-11-08: improve ours where we can)

Correction to the design notes above: the repo already has `listing_venue` (point-in-time exchange spans, migration 408) and `listing_end` (last listed session with reason and evidence, append-only, migration 518). Reuse them; do not coin "listing" for anything else. A symbol change is today "a spelling in `provider_meta`".

In order of value:

1. **Identity in three levels** (glossary entries first, per the naming rule; today no CIK, FIGI, CUSIP or ISIN is stored for any of the 1,529 instruments, and `provider_meta` is nearly empty):
   - `issuer`: CIK and LEI, the legal entity; survives renames. Company-level data (filings, fundamentals, market cap) hangs here.
   - `security identifier`: share class FIGI (never changes), CUSIP and ISIN (can change on corporate actions), each dated `[valid_from, valid_to)`, append-only. Bars attach here through the dated ticker map.
   - ticker history: a dated `ticker_event` table (renames and reuse) replaces the `provider_meta` spelling. Venue stays `listing_venue`.
   - Sources: Massive ticker details and ticker events (FIGI, share class FIGI, CIK, list date, delisted date); IBKR contract details for CUSIP and ISIN as a free cross-check (not captured today). Store reference responses raw, as served.
2. **Definition epochs.** A small dated table per vendor and column recording semantic changes (volume units after Massive's 2026-02-23 fractional shares; bid and ask sizes in shares from 2025-11-03; the 23/5 session from 2026-12-06), so features cannot mix definitions silently. The revision log covers restated values, not changed meaning.
3. **Session calendar as data.** A dated session definition (RTH, 23/5 from 2026-12-06, holidays and early closes) read by selection, instead of rules in code.
4. **`trade_count`** (Massive `transactions`, Alpaca `n`) as a nullable column on `ohlcv_raw`; feeds scrub rules and liquidity features; kept out of compute until a consumer exists. Alpaca `vw` the same.
5. **Completeness by file manifest** for Massive: day file exists, parses, row count, hash. Replaces the ask-ledger logic for the spans Massive owns.

Not copied: versioned dataset paths (`_v1`) stay inside the leaf, never in table names.
