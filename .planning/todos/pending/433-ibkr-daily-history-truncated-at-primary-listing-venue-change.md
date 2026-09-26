---
status: pending
priority: P1
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
- The history screen (`universe_expansion_history_screen.py`) would fail such a name as
  having no history before its cutoff, which biases small-cap draws against names that
  changed venue.
- Unknown how many of the 273 older names have the same gap.

## Next

1. List every active equity whose first 1d bar is later than its known trading start.
   Needs a listing-date source, or the head timestamp as a weak proxy.
2. Test whether IBKR serves the earlier history through another contract route, e.g. a
   request pinned to the old `primaryExchange`, or the old conId if IBKR keeps it.
3. If no route exists, record the truncation per symbol so panels can tell "listed late"
   apart from "venue moved".
