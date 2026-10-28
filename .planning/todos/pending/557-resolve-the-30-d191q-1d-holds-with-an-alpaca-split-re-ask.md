---
status: pending
priority: P2
filed: 2026-10-28
source: review of todo 545 for the data lane; owner chose to defer (2026-10-28)
---

# Resolve the 30 D-191-Q daily holds (Alpaca split re-ask and corporate-action judge)

## What

The 2026-10-28 arbitration plan (`data/policy_plans/d191q_1d_plan_20261028.json`) holds 30 daily
spans on about 30 names; a hold means Alpaca does not serve and the span has no daily bar until a
final row exists. Owner 2026-10-28: not worth delaying todo 545; revisit once testing runs.

- 21 `three_way` and `two_vendor` spans: both vendors hold the bars at different price levels.
  Split-type offsets (ELS and QBTS, IJR, NEXN, SNEX) are settled by asking Alpaca for daily bars
  with `adjustment=split` (the provider supports `split` and `raw`; the 545 build notes list "no
  Alpaca 1d split re-ask") and comparing with IBKR. Spin-off and merger offsets (BDX, CTVA, FTI,
  XPO, RTX, LEN, JCI, POST) need a recorded corporate action as the judge (545 step 5a), not a fetch.
- 9 `pre_ibkr_history` spans (CRH, GRNT, MDU, MSGS, ONTO, QRVO, SW, TPL, ZWS): IBKR has no bar
  before its head, so a fetch cannot help; the question is whether Alpaca's early history is the
  same company (ticker handover). A listing or corporate-action record answers it.

## Why not now

Both vendors' raw bars are kept in `ohlcv_raw`, so nothing is lost by waiting. The re-ask is a new
fetch and compare path with its own review, and 545 gates daily testing for all 1,529 names.
Resolve after the Tradier delete and the 1d re-derive, from corporate-action records.

## Done when

Each of the 30 spans has a final policy row or a recorded reason it stays empty; the plan JSON
is kept in a tracked location (545 review finding).
