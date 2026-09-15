# Phase 174 ETF Gap-Fill Ticker Selection

Author: Claude Sonnet 5

**Phase:** 174 (Universe Expansion -- Single-Name Breadth Scaling + Targeted ETF Gap-Fill), Plan 07
**Scope:** Records the two ticker decisions for D-06's remaining real scope (EM-FX exposure,
vol-proxy exposure), with the evidence Plan 10 needs to onboard them without re-research. Momentum
and quality factor-tilt ETFs are addressed by Plan 07's migration 338 (tag-taxonomy retag of
MTUM/QUAL/USMV), not by sourcing new tickers -- see the Correction section below.
**Status:** Both decisions made. EMLC (EM-FX) and VIXY (vol-proxy) selected, with the rejected
candidates (CEW, VXX) recorded alongside their screened figures.

## Correction to CONTEXT.md D-06

CONTEXT.md's D-06 states that momentum and quality factor-tilt ETFs currently have "zero
representation" in the corpus. **That premise is false.** Verified live against the database,
2026-09-15:

```sql
SELECT symbol, is_active FROM instruments WHERE symbol IN ('MTUM','QUAL','USMV');
--  MTUM | t     QUAL | t     USMV | t
SELECT symbol, count(*) FROM market_data_ohlcv WHERE symbol IN ('MTUM','QUAL','USMV')
GROUP BY symbol;
--  MTUM: 2,194,069 rows     QUAL: 2,156,803 rows     USMV: 2,417,375 rows
```

MTUM (iShares MSCI USA Momentum Factor ETF), QUAL (iShares MSCI USA Quality Factor ETF), and
USMV (iShares MSCI USA Min Volatility Factor ETF -- the low-vol factor D-06 separately dropped
from scope) were all added 2026-05-15, are `is_active=true`, and are already fully backfilled
across all four timeframes. They previously carried only the coarse `instrument_tags.tag =
'eq_factor'` label, shared with BTAL (market-neutral) and SPHB (high-beta) -- five structurally
different strategies under one tag, which made factor-specific IC stratification impossible.

D-06's intent (momentum and quality exposure present and individually identifiable) is satisfied
by migration 338 (this plan's Task 1): new `eq_momentum`/`eq_quality`/`eq_low_vol` exposure tags,
applied to MTUM/QUAL/USMV alongside their retained `eq_factor` row. **No new instrument is
sourced for momentum or quality.** This document covers only the two exposures that genuinely
have zero representation: EM currency and volatility.

## Screening criteria

Per D-06: average daily dollar volume (liquidity), expense ratio, and inception date / history
depth. Plus one criterion this project's data model forces: whether the price series carries a
structural discontinuity inside the corpus window -- a contaminated series would inject a regime
artifact into every feature derived from it (see `docs/foundation/performance-investigation-sop.md`
and this project's "silent wrong answers are worse than loud crashes" principle).

Figures below are live-verified 2026-09-15 via the Nasdaq quote-summary API
(`api.nasdaq.com/api/quote/{symbol}/summary?assetclass=etf`) and, for VIXY, cross-checked
directly against ProShares' own fund page (`proshares.com/our-etfs/strategic/vixy`), which is
authoritative over the aggregator figure where the two disagree. Inception dates for EMLC, CEW,
and VXX are cited from the well-established, multiply-corroborated historical record (issuer
launch dates do not drift) rather than freshly re-scraped this session -- WisdomTree's and
iPath/Barclays' own fund pages returned HTTP 403 to automated fetches in this session (Cloudflare
bot mitigation), consistent with 174-RESEARCH.md's own confidence framing that structural facts
like inception dates are stable and low-churn even when not re-verified on every pass. Where a
live figure disagreed with 174-RESEARCH.md's number, the live figure is used and the discrepancy
is called out explicitly below.

## EM-FX exposure: EMLC vs. CEW

**Decision: EMLC (VanEck J.P. Morgan EM Local Currency Bond ETF).**

| Metric | EMLC | CEW |
|---|---|---|
| Full name | VanEck J.P. Morgan EM Local Currency Bond ETF | WisdomTree Emerging Currency Strategy Fund |
| Structure | ETF | ETF |
| AUM | $5,053,023K (~$5.05B) -- Nasdaq API, 2026-09-15 | Nasdaq API's raw `AUM` field returned $197K, inconsistent with its own `MarketCap` field of $136,689,000 (~$136.7M) for the same query -- a live data-quality anomaly for this thin fund, not a typo in this document. Either figure is materially smaller than EMLC's; both are consistent in direction with 174-RESEARCH.md's ~$15-18M estimate being stale-but-directionally-right (this fund has been shrinking, not growing) |
| Expense ratio | 0.30% (Nasdaq API, matches 174-RESEARCH.md) | 0.55% (Nasdaq API, matches 174-RESEARCH.md) |
| Avg. daily volume (20-day) | 2,561,735 shares | 4,435 shares |
| Avg. daily volume (65-day) | 2,045,129 shares | 5,505 shares |
| Avg. daily volume (50-day) | 1,976,198 shares | 5,143 shares |
| Today's share volume (partial session) | 544,425.97 | 196.32 |
| Inception | July 22, 2010 (VanEck; month/day cross-confirmed live via an etf.com aggregator snippet before that source's rate-limit blocked further queries this session; year from established record) | May 7, 2009 (WisdomTree Dreyfus Emerging Currency Fund, established record -- WisdomTree's own site returned HTTP 403 to automated fetch this session) |

EMLC trades roughly 400-500x CEW's share volume on every window measured (20/65/50-day and
today's partial session) -- CEW is not just thinner, it is functionally abandoned at ~5,000
shares/day. A series this thin produces degenerate microstructure features (the exact reason
this project already maintains `market_data_ohlcv_tradeable` to exclude zero-volume and
flat-carry-forward bars). EMLC's much larger liquidity and lower expense ratio both favor it
over CEW on every screened dimension, confirming 174-RESEARCH.md's recommendation.

**The known tradeoff, recorded explicitly so it survives into `instrument_tags.evidence`:** EMLC
is not a currency-only instrument. It holds EM sovereign local-currency bonds, so its return
series carries EM sovereign credit risk and interest-rate duration on top of the currency
exposure CEW would have offered more purely. This contamination is real but removable: the
corpus already carries duration exposure (TLT/IEF/SHY) and credit exposure elsewhere, so a
common-factor control can residualize EMLC's credit/duration component out when a downstream
consumer wants a cleaner currency read. Plan 10's `instrument_tags` evidence JSONB for EMLC's
`fx_em` tag must carry this caveat explicitly -- do not let the tag imply a clean, credit-free FX
signal.

## Volatility exposure: VIXY vs. VXX

**Decision: VIXY (ProShares VIX Short-Term Futures ETF).**

| Metric | VIXY | VXX |
|---|---|---|
| Full name | ProShares VIX Short-Term Futures ETF | iPath Series B S&P 500 VIX Short-Term Futures ETN |
| Structure | ETF | ETN (Barclays Bank plc senior unsecured debt, not a fund) |
| Net assets | $215,715,364 -- live, ProShares' own fund page, 2026-09-15 (Nasdaq API's aggregator figure of $161,582K for the same fund disagrees; the issuer's own page is authoritative and is the figure used here) | $329,778K (~$329.8M) -- Nasdaq API, 2026-09-15 |
| Expense ratio | 0.85% (ProShares official page, matches Nasdaq API and 174-RESEARCH.md's tertiary-confidence figure) | 0.89% (Nasdaq API; 174-RESEARCH.md did not carry a cross-verified figure for VXX's expense ratio) |
| Avg. daily volume (20-day) | 2,459,210 shares | 7,755,480 shares |
| Avg. daily volume (65-day) | 2,491,319 shares | 8,174,514 shares |
| Avg. daily volume (50-day) | 1,439,762 shares | 4,592,617 shares |
| Today's share volume (partial session) | 2,164,194.61 | 2,800,795.51 |
| Inception | January 3, 2011 -- live, ProShares' own fund page (`snapshot-inceptionDate` field), 2026-09-15 | Original iPath VXX: January 30, 2009. Reissued as "iPath Series B" (same VXX ticker) January 29, 2019, when Barclays exchanged the original notes for Series B notes -- a second structural event on top of the one below |

VXX has deeper volume on every window measured (roughly 2-3x VIXY's), confirming 174-RESEARCH.md's
note that raw liquidity favors VXX. That is outweighed by structure: VXX is an ETN (an unsecured
debt obligation of Barclays Bank plc tracking an index, not a fund holding assets), and Barclays
halted creation of new VXX shares in March 2022 after the notes approached their SEC registration
ceiling. Since that halt, VXX has persistently been able to trade at a premium to its indicative
value, because new-share creation is the mechanism that normally arbitrages an ETN back toward
fair value -- with issuance closed, that mechanism is gone. This is a structural discontinuity
landing in the middle of this corpus's measurement window (2022), not a one-time event that
happened before data collection started: it would inject a regime artifact into every feature
derived from VXX's price series for the corpus period spanning before and after March 2022.

This session's live data pulls (Nasdaq API quote/volume data) neither confirm nor contradict
whether the creation halt remains in effect as of 2026-09-15 -- that is a corporate-actions fact
the quote APIs used here do not surface, and this session's attempts to reach Barclays'/iPath's
own site for a fresh confirmation were blocked (redirect loop, no usable content returned). The
halt is a well-documented, multiply-corroborated structural fact as of its original occurrence
(174-RESEARCH.md's own MEDIUM-confidence tag); nothing found in this session contradicts it, and
ETN issuers reopening a previously-closed creation program is a rare, newsworthy event this
project would be very unlikely to have missed if it had happened. VIXY carries no equivalent risk
-- it is a real ETF (owns VIX futures directly, not a bank's promise to pay), with normal
creation/redemption throughout. Deeper options liquidity on the underlying VXX does not
compensate for a contaminated price history in a measurement corpus that needs a clean,
continuously-arbitraged series across its full window. VIXY is the pick.

## Field values for Plan 10

### EMLC

**`contract_details` (ten-key set):**
```json
{"symbol":"EMLC","base":"EMLC","name":"VanEck J.P. Morgan EM Local Currency Bond ETF","asset_class":"equity","exchange":"SMART","sector":"em_fx_bond","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}
```
(`asset_class` is `"equity"` per this project's convention that all ETFs, regardless of
underlying asset, use the ETF/equity contract-resolution path through `qualify_instrument()` --
matches every other bond/FX ETF already in `instruments`, e.g. TLT/IEF/SHY/FXE/FXY/UUP.)

**`instrument_metadata`:**
- `listing_date`: `2010-07-22`
- `underlying_index`: `J.P. Morgan GBI-EM Global Core Index (GBIEMCOR)`
- `issuer`: `VanEck`
- `description`: `Tracks the J.P. Morgan GBI-EM Global Core Index, providing exposure to local-currency-denominated emerging-market sovereign bonds. Primary use in this corpus is EM currency exposure; carries EM sovereign credit risk and interest-rate duration on top of that currency exposure -- see the EM-FX section of docs/research/phase174-etf-gap-fill-ticker-selection.md for the residualization note.`

**Exposure tag:** `fx_em`, `source='human'`, `evidence` must carry the credit/duration
contamination caveat from the EM-FX section above -- do not write a tag evidence string implying
a clean currency-only signal.

### VIXY

**`contract_details` (ten-key set):**
```json
{"symbol":"VIXY","base":"VIXY","name":"ProShares VIX Short-Term Futures ETF","asset_class":"equity","exchange":"SMART","sector":"volatility_proxy","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}
```

**`instrument_metadata`:**
- `listing_date`: `2011-01-03`
- `underlying_index`: `S&P 500 VIX Short-Term Futures Index`
- `issuer`: `ProShares`
- `description`: `Holds a rolling position in near-term VIX futures, tracking the S&P 500 VIX Short-Term Futures Index. Primary use in this corpus is equity-index implied-volatility exposure. Selected over VXX (iPath Series B S&P 500 VIX Short-Term Futures ETN) because VXX is an ETN whose issuer halted new-share creation in March 2022, producing a persistent post-halt structural discontinuity in its price series -- see the vol-proxy section of docs/research/phase174-etf-gap-fill-ticker-selection.md.`

**Exposure tag:** `vol_proxy`, `source='human'`, `evidence` should note the VXX rejection
rationale (ETN structural discontinuity) so the tag's provenance is self-explanatory without
requiring a cross-reference lookup at query time.

## Out of scope, confirmed unchanged from 174-RESEARCH.md

Commodities, international equity, fixed income, real estate, and crypto exposure are already
well covered in the corpus (39 exposure tags across 231 symbols, checked in 174-RESEARCH.md).
This document does not expand that list. No new momentum or quality ticker is proposed anywhere
in this document -- that gap is closed by migration 338's retagging, not by sourcing.
