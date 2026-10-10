# Databento API reference card

Version: 5.61.0
Status: draft (partially verified; key created 2026-10-10, nothing integrated
yet)
Author: Brandon with Claude Code (session, 2026-10-10)
Informed by: databento.com/docs pages fetched 2026-10-10 via browser
(schemas-and-data-formats/ohlcv, venues-and-datasets/equs-summary,
venues-and-datasets/equs-mini). The docs portal is a JS app: plain HTTP
fetches get a shell; render a browser or use search-engine caches. Anything
marked **unverified** gets measured in a probe before it enters a plan.

## Credential

- Key `IndicAgent` created 2026-10-10 (portal user `HLAK4R4E`), stored in
  `.env` as `DATABENTO_API_KEY` (gitignored; never in docs, memory, or
  code). The key is the sole credential; consumed via
  `src/config/Settings` when an integration lands, never `os.environ`.

## Verified (fetched 2026-10-10)

- **OHLCV schemas are 1s/1m/1h/1d only; no 5m schema.** Their own
  recommendation for 5m: aggregate client-side from `ohlcv-1m`. Any
  Databento 5m we store therefore arrives as a derivation, which matches
  the repo's derivation discipline (`session_grid.py`'s session-anchored
  buckets are the house convention, not midnight-UTC floors).
- **Bars aggregate from trades; no record prints for an interval with no
  trade.** Absence semantics align with the `no_fill` invariant (missing
  is missing), but means Databento interval grids are trade-shaped, not
  slot-complete; the gap planner's grid, not the vendor's, is truth.
- Prices are int64 fixed-point at 1e-9.
- **`ohlcv-1d` is UTC-date based, not exchange-session.** Their docs say
  outright that session-hour daily bars require aggregating a finer schema
  yourself. Databento 1d is therefore never a drop-in rival to IBKR's 1d
  primary.
- Datasets relevant to US equities:
  - `EQUS.MINI`: derived top-of-book (BBO/TBBO/MBP-1/Trades plus the
    OHLCV schemas), proprietary blend of ATS and RegNMS direct feeds,
    aggregated across component venues; trade venue anonymized.
    This is the intraday source candidate.
  - `EQUS.SUMMARY`: Nasdaq NLS+ consolidated end-of-day only (schemas:
    ohlcv-1d, statistics, definition). Their ohlcv-1d comes from the final
    20:15 ET NLS+ summary and includes post-market volume, a known
    divergence source vs session-bounded dailies.
- Symbol convention in equities datasets is Nasdaq-style raw symbols
  (`BRK.B`, `AAC+`); symbology conversion is per-dataset.

## Unverified (probe before any plan cites)

- Pricing at our volume (1,529 names; EQUS.MINI ohlcv-1m RTH, full depth).
- Equities history depth start per dataset (does EQUS.MINI reach past
  Alpaca's 2016-01-01 floor?).
- Historical API endpoint shape and batch mechanics; live gateway (recorded
  but irrelevant while streaming is dormant).

## Why it matters here

First candidate third data vendor; lands in the bars vendor lists (unlike
Clear Street). Candidate roles: intraday depth beyond Alpaca's 2016 floor,
and a second tape for vendor-agreement audits (the d2/D7 basis machinery
generalizes). Admission follows the Alpaca path: `source_admission.py`
gates plus a measured basis study, then one `VendorIngress` seam row
(`src/intelligence/bars/vendor_ingress.py`). No admission without the
measured basis study.
