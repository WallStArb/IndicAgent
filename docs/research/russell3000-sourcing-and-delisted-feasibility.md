# Russell 3000 Sourcing Schema + Delisted-Constituent Feasibility

Author: Claude Sonnet 5

**Version:** 1.0
**Status:** both open questions answered with live evidence — Russell 3000 sourcing schema
confirmed against the real downloaded file; delisted-data feasibility verdict is UNRESOLVED
(not NOT OBTAINABLE), with a concrete next step named
**Phase:** 174 (Universe Expansion — Single-Name Breadth Scaling + Targeted ETF Gap-Fill), Plan 04
**Scope:** answers RESEARCH.md Open Question 1 (Russell 3000 population sourcing schema) and
todo 376 action item 1 (delisted-constituent data feasibility) only. Does not change Phase
174's pilot scope — see the explicit statement in the Delisted-constituent feasibility section
below.
**Date:** 2026-09-15

## Russell 3000 population sourcing

### Source and endpoint

The iShares IWV (Russell 3000 ETF) public holdings export is the source of truth for Russell
3000 membership (RESEARCH.md "Don't Hand-Roll" table), per D-02. Two endpoints were tried live
this session:

1. **`https://www.ishares.com/us/products/239714/ishares-russell-3000-etf/1467271812596.ajax?fileType=csv&fileName=IWV_holdings&dataType=fund`**
   — the plausible-looking guessed AJAX endpoint. Returns HTTP 200 with `Content-Type:
   text/csv;charset=UTF-8`, but the actual response body (~1.4MB, both with and without a
   pre-warmed cookie jar from the product page) is an HTML single-page-app shell, not CSV data.
   iShares/BlackRock sits behind a bot-mitigation layer (SourceDefense, visible in response
   preconnect headers) that serves this shell to non-browser clients even on this endpoint.
2. **`https://www.ishares.com/us/products/239714/ishares-russell-3000-etf/latest-holdings.csv`**
   — the real download link, found by fetching the live product page and grepping for the
   actual `href` the page's own "Download Holdings" control points to
   (`/us/products/239714/ishares-russell-3000-etf/latest-holdings.csv`). Returns the real CSV
   file directly, no session cookies or JS execution required. **This is `DEFAULT_URL` in
   `scripts/infrastructure/universe_expansion_fetch_iwv_holdings.py`.**

This is a load-bearing finding for anyone re-verifying or extending this script: **Content-Type
is not a reliable discriminator between the real file and the fake challenge shell** — the fake
shell claims `text/csv`, the real file claims `text/plain; charset=utf-8`. The check that
actually distinguishes them is a body sniff for a leading `<html` marker in the first 512
bytes, implemented in `_validate_response()`.

### Real file facts (observed 2026-09-15, live download)

- **HTTP status:** 200
- **Content-Type:** `text/plain; charset=utf-8`
- **Body size:** 399,024 bytes
- **Encoding:** decoded cleanly as `utf-8` (the `latin-1` fallback was not exercised — plain
  ASCII content, no accented issuer/company names in this pull)
- **Header row index (0-indexed):** 9 — iShares prepends 8 lines of fund-level metadata (fund
  name; "Fund Holdings as of"; inception date; shares outstanding; Stock/Bond/Cash/Other
  asset-class totals) plus one blank separator line before the real column header.
- **Verbatim column list:** `Ticker, Name, Sector, Asset Class, Market Value, Weight (%),
  Notional Value, Quantity, Price, Location, Exchange, Currency, FX Rate, Market Currency,
  Accrual Date`
- **Total data rows:** 2,580
- **Non-equity filler rows:** 5 — 2 `Futures` (RTY and ES E-mini overlay positions), 1 `Money
  Market`, 1 `Cash`, 1 `Cash Collateral and Margins`. None of these are Russell 3000
  constituents; all are dropped by `parse_holdings()` and counted, not silently discarded.
- **Rejected rows (malformed ticker or non-finite/non-positive market cap):** 11 — a mix of
  placeholder `"-"` tickers for unlisted/escrow/CVR line items (e.g. private-placement vesting
  shares, contingent-value-right positions carried at near-zero notional) that fail the
  `^[A-Z][A-Z0-9.\-]{0,9}$` ticker regex.
- **Accepted rows (final population frame):** 2,564

### Market-cap decision

**`Market Value` is used directly, with no derivation, no fund-AUM lookup.**

This column is the fund's dollar position in each holding (`shares_held_by_fund × price`), not
the constituent company's total market capitalization in absolute dollars. For a cap-weighted
index fund like IWV, though, per-holding `Market Value` is linearly proportional to each
constituent's true market cap — proportional by a single constant scalar
(`fund_AUM / total_index_market_cap`) that is identical across every row. Because Plan 08's
stratified sampling only needs *relative* company-size ranking (decile bucketing via
`pandas.qcut`), not the constituent's literal market cap in dollars, this linear
proportionality means `Market Value`-based deciles are identical to true-market-cap-based
deciles. No `weight_pct × fund_AUM` derivation, and no external shares-outstanding lookup, is
needed.

**Caveat for anyone reusing this column for a different purpose:** if a future consumer needs
the constituent's actual company-level market capitalization in dollars (not just a relative
rank), `Market Value` from this file is the wrong number to use directly — it reflects IWV's
fund size, not the company's total shares outstanding × price. `Weight (%)` combined with an
independent market-cap figure (or `Notional Value`, present in this file but numerically
identical to `Market Value` for every row observed) would still require the same AUM-scaling
correction. Plan 08 should carry this caveat forward if the stratification design changes to
need absolute market cap rather than relative rank.

### Reproducing this

```bash
.venv/bin/python scripts/infrastructure/universe_expansion_fetch_iwv_holdings.py --dest /var/tmp/iwv_holdings.csv
```

`fetch_holdings()` and `parse_holdings()` are both independently importable
(`scripts.infrastructure.universe_expansion_fetch_iwv_holdings`) for Plan 08's stratified
sampling script to consume directly.

## Delisted-constituent feasibility

### Method and evidence

Three concrete US equities delisted or acquired within the corpus's historical window were
selected, spanning both delisting mechanisms named in the action item (acquisition-completed
and bankruptcy/failure-driven):

| Ticker | Company | Delisting event | Approximate delisting date |
|--------|---------|------------------|----------------------------|
| SIVB | SVB Financial Group (Silicon Valley Bank) | FDIC receivership / bank failure | 2023-03-10 (trading halted same day; formally delisted from Nasdaq shortly after) |
| TWTR | Twitter, Inc. | Acquisition completed (Elon Musk take-private) | 2022-10-28 |
| ATVI | Activision Blizzard, Inc. | Acquisition completed (Microsoft) | 2023-10-13 |

**1. Live IBKR test — NOT ATTEMPTED, gateway down.** `docker ps -a` confirms `ib-gateway` is
`Exited (1) 7 days ago` as of this session (2026-09-15), consistent with RESEARCH.md's Pitfall
4 finding (stopped 2026-09-07 as part of the todo-371 OOM workaround). Per this plan's explicit
instruction, `ib-gateway` was **not** restarted for this task — Plan 10 owns that restart, and
this research must not contend for the critical path. No `qualify_instrument()` or
`fetch_historical_bars()` call was made against any of the 3 tickers. This is the one arm of
the investigation this document cannot yet answer empirically.

Structural note for whoever runs this test once the gateway is back up: `src/providers/ibkr.py`
resolves every fetch through `qualify_instrument()` first (`src/providers/CLAUDE.md`), which
depends on IBKR returning valid live contract details for the requested symbol. A permanently
delisted equity has no live contract for IBKR to resolve — whether this causes qualification to
fail outright (most likely, based on how IBKR's contract-details API is documented to behave
for non-current symbols generally, per the paper-account Error-200 precedent already recorded
for `BZJ6`/`NGJ6`/`SR1H6` in `src/providers/CLAUDE.md`) or whether IBKR retains and serves
historical bars for a symbol it can no longer qualify live is exactly the open question a real
test against SIVB/TWTR/ATVI would answer.

**2. Free/standard alternative source — tested live, confirmed NOT available.** Yahoo Finance's
public chart API (`query1.finance.yahoo.com/v8/finance/chart/<symbol>`), commonly used as a
free historical-bars source, was queried directly for all 3 tickers:

```
GET https://query1.finance.yahoo.com/v8/finance/chart/SIVB?period1=1609459200&period2=1680000000&interval=1d
→ HTTP 404: {"chart":{"result":null,"error":{"code":"Not Found","description":"No data found, symbol may be delisted"}}}

GET .../chart/TWTR?... → identical 404, identical error
GET .../chart/ATVI?... → identical 404, identical error
```

All three returned the identical explicit error, confirming Yahoo's free API drops historical
data entirely once a symbol delists — this is not a rate-limit or access issue, it is the
API's documented behavior for delisted symbols.

`stooq.com` (a second free historical-data source) was also attempted for all 3 tickers; every
request was intercepted by a client-side proof-of-work JavaScript challenge
(`crypto.subtle.digest` SHA-256 puzzle solved in-browser before the real response is served),
which cannot be completed by a non-browser HTTP client without executing arbitrary JS. This
source could not be evaluated either way from this session.

**3. Cost of a source that would work.** Free consumer sources (Yahoo, and by extension most
free stock-quote APIs, which generally re-derive their universe from currently-tradable
symbols) structurally drop delisted names. Delisted/survivorship-bias-free historical equity
data is a known paid-data-vendor category, not a free-tier feature — CRSP (the academic-standard
survivorship-bias-free US equity database), Norgate Data (explicitly markets "no survivorship
bias" daily-bar datasets as a paid subscription), and premium tiers of commercial data APIs
(Polygon.io, EODHD) are the standard providers for this specific need. None of these were
signed up for or tested against live data in this session — doing so would require creating a
paid or trial account, which is out of scope for a research task and was not attempted.

### Verdict: UNRESOLVED

Evidence gathered this session rules out the free/convenience path (Yahoo: confirmed
structurally absent; stooq: inaccessible without JS execution) but does not yet answer whether
IBKR itself can serve this data (gateway down, not tested per this plan's explicit
instruction) or what a paid vendor's actual delisted-coverage would cost and how it would need
to be integrated. This is neither OBTAINABLE (nothing has actually been obtained) nor NOT
OBTAINABLE (the most plausible paths — IBKR once the gateway is back, or a paid vendor — remain
untested, not failed).

**What is still needed to resolve it, concretely:**
1. Once `ib-gateway` is restarted (Plan 10's responsibility, not this task's), run
   `qualify_instrument()` + a bounded `fetch_historical_bars()` call against SIVB, TWTR, and
   ATVI and record the literal IBKR response (contract resolved / an Error-200-class
   ambiguous-contract error / an empty bar set with a resolved contract). This is a 10-minute
   test once the gateway is up, not a research project.
2. If IBKR fails, evaluate one paid vendor's actual delisted-security coverage against a trial
   or minimal paid tier (Norgate Data and Polygon.io are the two most directly comparable to
   this project's existing daily/intraday-bar needs) before concluding NOT OBTAINABLE.

### Explicit scope statement

**Per D-03, this verdict does not change Phase 174's pilot scope.** The pilot sample stays
active-only (today's Russell 3000 constituents), regardless of what this verdict eventually
resolves to. A future OBTAINABLE verdict would become an input to a later, separate decision
about whether to fold a delisted-name sample into the corpus and re-run a closed construction
(todo 376 action item 2) — it is not, by itself, authorization to expand this phase's scope.

## Cross-references

- `.planning/todos/pending/376-survivorship-bias-active-only-universe-no-owner.md` — the todo
  this document's Delisted-constituent feasibility section directly answers action item 1 for.
- `.planning/phases/174-universe-expansion-single-name-breadth-scaling-targeted-etf-/174-RESEARCH.md`
  — Open Question 1 (Russell 3000 sourcing schema) and Pitfall 4 (`ib-gateway` down).
- `scripts/infrastructure/universe_expansion_fetch_iwv_holdings.py` — the fetch/parse module
  whose schema decisions this document records.
