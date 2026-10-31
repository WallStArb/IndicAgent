---
status: completed
priority: P2
filed: 2026-10-09
source: 189-10 Task 2 pilot C7 results (b3e46fa4f)
---

# Intraday parity follow-up: vendor volume basis (WEAT) and dividend-era price buckets

## What

C7 grid parity failed on 6 of 11 compared names. The diagnostic split shows two distinct causes the
derivation is not responsible for (C6c proves the derivation faithful):

- WEAT: 12,207 of 12,207 mismatched 15m buckets (and 6,332/6,332 1h) are volume-only; prices match
  exactly. A vendor-vs-IBKR volume basis difference (route vs consolidated tape), not an error.
- AAPL, SPY, CEG, APH, EWL: handfuls (1-9) of price-only buckets, consistent with vendor-adjusted
  ex-dividend buckets against our price-only bars.

Decide whether archive parity tolerates a recorded per-name volume basis difference or the archive
rebuckets to IBKR volumes; decide the dividend-bucket policy (tolerate as explained, or gate parity
to non-ex-dividend spans). Both belong next to the C7 verdict semantics, with the split recorded in
the D7 output, not re-derived by hand.

## Done when

D7's grid_parity verdict carries the price/volume split and a recorded tolerance rule; the rule is
dated before it is applied (same discipline as todo 512's exclusion rule).

## Status 2026-10-22 (phase 191 plan 18)

The data half landed with phase 191: the 15m/1h parity lane serves into `ohlcv_raw` (verified
by plan 16's explicit URA run; the old archive table is dropped), so the parity inputs are raw
rows under (vendor, kind). Still open, explicitly deferred as D-191-H (planner decision, owner
acknowledgement pending): D7's dated tolerance rule for the per-name volume basis and the
price/volume split in its output. The todo stays open for that remainder.

## Done 2026-10-31 (D7 dated tolerance landed)

The dated tolerance rule landed the same day the todo 573 classification dated it, before it was
applied. `grid_parity` takes dated exceptions and counts them separately
(`src/intelligence/bars/integrity_checks.py`): a mismatch on a stamp the record file dates, or on
a bucket whose archive row's `served_at` predates the day's 5m bars (superseded evidence,
`superseded_archive_buckets`), is excepted, never gating; prices stay exact everywhere else. The
recorded half lives in `config/bars/grid_parity_dated_exceptions.json` (recorded 2026-10-31, all
644 classified stamps with their price/volume split; waves 1 and 2 released, wave 3 ETHA/CTVA
held until their archive rows are re-fetched). The audit loads the file, reports the excepted
count per timeframe in `bar_integrity.report_intraday`, and the verdict metric stays the
unexcepted mismatch count. The 2026-10-22 volume-basis question closed earlier: the volume slack
(n-1 shares) landed with todo 569 and the residual disagreement is the dated artifact above.
