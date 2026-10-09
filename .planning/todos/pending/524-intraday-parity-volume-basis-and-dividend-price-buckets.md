---
status: pending
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
