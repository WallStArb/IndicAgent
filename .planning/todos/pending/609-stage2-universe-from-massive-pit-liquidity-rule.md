---
status: pending
priority: P1
filed: 2026-11-12
source: owner 2026-11-12 ("30,000++ securities from Massive, 1,500 on IBKR"); todo 600 stage 2; lead ruling
---

# Stage 2 universe: a point-in-time, survivorship-free universe from the Massive archive

## Why

The archive holds 30,000+ tickers over 2003-2026; our canonical universe is 1,529 current names (stage 1 only deepens their history, it does not remove survivorship or add breadth). Breadth (more independent bets) and a survivorship-free sample are the two largest levers on finding significant edge, and the archive is already paid for and verified. Measured 2026-11-12 on the day files: a typical session carries about 10,500 tickers in 2024 and 7,800 in 2008 and 2015; names with close x volume above $1M a day number about 4,900 (2024) and 4,500 (2015), above $10M about 2,600 and 2,300, above $100M about 800 and 600. So the investable set is a few thousand names a day, not 30,000; the rest is warrants, units, preferreds, ETNs and micro-caps.

## Measured 2026-11-12 (the proposed rule on the 50.2M day-file rows, 36,735 tickers, month-end membership)

Rule: month-end t, 60-session median of close x volume at or above the floor, close at or above $1, at least 60 sessions. Matched to our 1,529 by ticker symbol (a reused ticker can match falsely), no security-type filter yet (a plain-ticker proxy, letters only and at most 5 characters, barely moves the counts).

| Floor | Distinct names ever in | Already ours | NEW | Members per month-end (median, min, max) |
|---|---|---|---|---|
| $1M | 16,045 | 1,525 | 14,520 | 4,154 (2,947 to 6,041) |
| $5M | 10,231 | 1,481 | 8,750 | 2,616 (1,588 to 4,169) |
| $10M (proposed) | 8,003 | 1,448 | 6,555 | 2,026 (1,033 to 3,454) |
| $25M | 5,525 | 1,355 | 4,170 | 1,313 (571 to 2,539) |

At the proposed $10M floor about 6,555 securities are new (dead and merged names, and names that were never on our list), about 2,000 are members at any month-end, and 1,448 of our 1,529 qualify. Owner 2026-11-12 agreed with this sizing; the floor itself is preregistered before any look. Ongoing capture for the new names after the Massive plan lapses is Alpaca (same upstream, nightly SIP); Massive plus Alpaca covers history and the forward feed.

## Ruling (lead 2026-11-12)

1. Raw is permanent and complete at 1d: load the 1d day files for every ticker in the archive into `ohlcv_raw` (about 50M rows, trivial). 5m is NOT loaded for all names (billions of rows); it follows the tier below.
2. The research universe is a rule, never a screen on returns: a point-in-time `universe_membership` table (month-end, as of t) built from Massive's own data. Proposed rule, frozen in a preregistration before any look and its thresholds APR keys: security type common stock or ETF from the Massive reference types; trailing 60-session median dollar volume at or above a floor (start at $10M, about 2,600 names a day); close at or above $1; at least 60 sessions of history. Delisted and merged names stay in while they meet the rule on the date, which is what removes survivorship.
3. Identity: the key rule for reused tickers uses the entity map (FIGI, ticker events, spans); a reused ticker is two securities. Dead-name instrument rows go through the onboarding SOP exception the design reserved for stage 2 (owner-approved, recorded); never hand-written `instruments` rows.
4. Tiers by cost: 1d for the whole membership (cheap, the first counted tests on daily families run here); 5m only for names in the top liquidity tier, sized by a measured `feature_vectors` cost estimate (5m is about 69 percent of the table today).
5. Executability: the floor is also the tradability floor for a personal book (spread, borrow); costs never enter a test statistic, but names below the floor are out of promotion.

## Failure modes to design against

Choosing the floor or type filter after seeing results (it is a counted design choice; fix it first); ticker reuse mixing two companies; point-in-time leakage (membership uses only data known at t, including the dollar-volume window); stage 2 loads moving canonical before step 7 proves; universe growth silently multiplying corpus compute (gate on the measured estimate); a delisted name's final bars (delisting return) missing from 1d.

## Gates

Step 7 and the 8a checks pass first (stage 1 is the data gate; this does not jump it). Then: the membership rule preregistered and recorded; the membership table built and its count by year reported; 1d raw loaded for all tickers with the load-engine gate per year (compare 0 real differences, canonical unchanged); a cost estimate for 5m and feature compute at the proposed tiers; owner sees the count by year before any compute.

## Next step

After 8a and step 7: write the preregistration (rule, thresholds, type source) and the 1d all-ticker load plan; extend `ops_massive_load.py` with an `--all-tickers` mode behind the identity map. Design hook: `docs/plans/2026-11-10-massive-admission-db-design.md` section 8b stage 2 and section 11.
