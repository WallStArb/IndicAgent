# Massive REST plan entitlements

**Status:** active reference, empirical, captured 2026-11-10 during the paid-plan month window
(todo 600). Rows are what the API answered on our plan on 2026-11-10, not what the docs claim.
**Author:** Claude worker session, 2026-11-10, executing the todo 600 entitlement probe and
capture brief.
**Informed by:** `data/massive/reference/capture_log.jsonl` (as-served responses, sha256 per
page), `data/massive/reference/manifest/20261110.jsonl` (the concurrent full-universe sweep by
a sibling session), todo 600, `docs/plans/2026-11-10-massive-admission-db-design.md`,
`docs/reference/data-adjacency-register.md`.

## Access facts

- Base URL `https://api.massive.com`. Auth: `Authorization: Bearer <MASSIVE_API_KEY>` or the
  `apiKey` query param, both accepted. `X-API-KEY` is not read.
- The paid plan is provisioned and confirmed from two sides: REST answers 200 across the
  reference surface, and S3 paid downloads on `files.massive.com` return 206 (2010 minute-agg
  file, 12,393,642 bytes, `x-amz-meta-entitlement-data-type: aggregates-minute`).
- Rate limits: the only observed headers were `x-ratelimit-limit: 50000`,
  `x-ratelimit-remaining: 50000`, `x-ratelimit-reset: 0`, served on `/v3/trades` and
  `/v3/quotes`; reference endpoints served no rate headers at all. 307 requests in this probe
  and the sibling session's ~150k-request sweep produced no 429. Treat REST as effectively
  unmetered within a month window, and still keep bulk pulls paginated and sequential.
- Pagination is Polygon-style `next_url` with opaque cursors; `limit=1000` on v3 reference,
  `limit=5000` on the `/stocks/v1` surface. `x-item-count` echoes the page row count.
- The whole reference tree is git-ignored (`data/`); persistence is the as-served files plus
  the sha256 sidecar, not git.

## Entitlement table

| Endpoint | Observed | Verdict |
|---|---|---|
| `/v3/reference/tickers` | 200, paginated, cik/composite_figi/share_class_figi per row | entitled |
| `/v3/reference/tickers/{ticker}` | 200 (AAPL sample captured) | entitled |
| `/v3/reference/tickers/types` | 200, 25 rows | entitled |
| `/v3/reference/tickers/events` (bulk) | 404 | not served; per-ticker `/vX/reference/tickers/{t}/events` is 200 and the sibling session swept all 36,869 tickers (13,829 with events) |
| `/v1/marketstatus/now` | 200 | entitled (the `/v3/reference/marketstatus` path from Polygon docs is 404) |
| `/v1/marketstatus/upcoming` | 200, per-exchange holidays with early closes | entitled |
| `/v3/reference/exchanges` | 200, 54 rows | entitled |
| `/v3/reference/conditions` | 200, 130 rows, single page | entitled |
| `/v3/reference/locales` | 404 | not served |
| `/v3/reference/sic` | 404 | not served |
| `/v3/reference/splits` | 200, full pull: 28,880 rows, 1978-10-25 to 2027-01-13 | entitled |
| `/v3/reference/dividends` | 200, paginated (241k+ rows seen descending from ex-date) | entitled |
| `/v2/aggs/ticker/{t}/prev` | 200 | entitled |
| `/v2/aggs/ticker/{t}/range/...` | 200 with dashed dates (`2025-01-02`); slash-separated `y/m/d` 404s | entitled, different date format than Polygon |
| `/v2/aggs/grouped/...` | 200, 10,870 tickers for 2025-01-02 | entitled |
| `/v3/trades` | 200, paginated | entitled |
| `/v3/quotes` | 200, paginated | entitled |
| `/v2/last/trade/{t}` | 200 | entitled (`/v3/last/*` is 404) |
| last quote | 404 on both `/v3/last/quote` and `/v2/last/quote` | not served |
| `/v2/snapshot/.../tickers/{t}` | 200 | entitled |
| `/v2/snapshot/locale/us/markets/stocks` (full market) | 404 | not served |
| `/v3/reference/financials`, `/v3/reference/news` | 404 | Polygon paths not served; see the `/stocks/` surface below |
| `/stocks/financials/v1/{income-statements,balance-sheets,cash-flow-statements,ratios}` | 200 across all 36,869 tickers (sibling sweep) | entitled |
| `/stocks/vX/float`, `/stocks/v1/short-interest`, `/stocks/v1/short-volume` | 200 across all tickers (sibling sweep) | entitled |
| `/stocks/v1/splits`, `/stocks/v1/dividends` | 200, bulk at `limit=5000` (sibling sweep) | entitled |
| `/vX/...` prefix | resolves like `v3` on every endpoint tried | live version alias, usable in stored URLs' place |

Two parallel surfaces matter for the design: the Polygon-compatible `/v2`+`/v3` reference and
aggs surface, and a Massive-native `/stocks/` surface (financials, float, short interest and
volume, a second splits and dividends family). Massive's tier docs describe neither precisely;
this table is the measured one.

## What was captured (as-served, `data/massive/reference/`)

This session, each page sha256'd in `capture_log.jsonl`:

- `splits/page0000-0028.json`: complete, 29 pages, 28,880 splits, 1978-10-25 through
  2027-01-13. Includes all five AAPL and all four NVDA splits; the same rows appear in the
  sibling session's `/stocks/v1/splits` pull, so the two Massive families agree. Both list
  NVDA only from 2006 back, so one independent cross-check on pre-2006 splits should precede
  any claim that Massive splits history is complete.
- `dividends/page0000-0240.json`: partial by design, 241 pages, 241,000 rows, descending by
  ex-date. The full set is bulk-served at `/stocks/v1/dividends` and captured there by the
  sibling session (147 pages at 5,000). Announced future ex-dates reach 2030.
- `ticker_types/all.json` (25), `exchanges/all.json` (54), `conditions/page0000.json` (130,
  complete in one page), `market_holidays/upcoming.json` (per-exchange, early closes
  included), `tickers_details/aapl.json` (schema sample: cik, composite and share-class FIGI,
  list_date, delisted_utc, type, primary_exchange).

The sibling session's sweep (its own manifest, `manifest/20261110.jsonl`): tickers active and
delisted (full), per-ticker ticker events for every ticker, IPOs (bulk), splits and dividends
via `/stocks/v1`, and financial statements, ratios, float, short interest and short volume for
all 36,869 tickers. The entity-map raw material todo 600 needs is therefore already on disk.

## Surprises

1. Future-dated corporate actions: splits carry execution dates out to 2027-01-13 and
   dividends out to 2030. A point-in-time join must gate on announcement/availability time,
   not execution date, or announced actions leak backwards.
2. `/v2/aggs` range silently 404s with Polygon's slash date format; dashed dates work. Any
   ported Polygon client needs that adapter.
3. Events exist only per ticker; there is no bulk event listing. The universe sweep is the
   only way to refresh the entity map, which makes the month window matter for it.
4. No locales, SIC codes, last quote, or full-market snapshot. Classification joins stay with
   our own SCH; there is no Massive substitute for them.
5. AAPL details carry `last_updated_utc: null` and the list response carries a real timestamp;
   availability time may need to come from the capture moment itself for details rows.
