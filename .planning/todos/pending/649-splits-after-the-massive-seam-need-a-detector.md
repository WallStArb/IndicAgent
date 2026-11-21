---
status: pending
priority: P1
filed: 2026-11-21
source: Alpaca nightly 2026-11-20 exited 1 (PARTIAL, one basis-change restatement flag, SNDK 5m); second case in two days after VIXM (todo 641)
owner: lead
---

# Splits after the Massive seam are found by a failed nightly, not by a detector

## What

SNDK split 8:1 (Yahoo ex-date 2026-11-20). Alpaca restated 576 stored 5m bars (price ratio 0.125, volume ratio 8) and the nightly exited 1 on the basis-change flag, load 6449933f. Canonical takes Massive to the 2026-11-16 seam (old scale, 1d close 885.01 on 2026-11-13) and Alpaca after (new scale, 101.14 on 2026-11-16), so canonical steps 8x at the seam. The A3 sweep cannot judge a series switch at the junction (no measured level on the Massive side), so the row is written by hand. Row file: `config/corporate_actions/split_rescale_rows_2026_11_21_sndk.csv` (factor 8, last old-scale session 2026-11-13, route massive/sip_flat), same procedure as VIXM.

## Why a class, not a name

The archive ends at the seam and the plan lapses about 2026-12-10, so every split from now on is in this class: Alpaca serves history already adjusted, stored Massive bars stay old scale, and the only alarm is the nightly's restatement flag (loud, but a human reads it, finds the witness and writes the row). Two in two days. Measure the base rate before building (splits and reverse splits per month across the active names, from the Alpaca corporate-actions feed or the Yahoo calendar), then decide.

## Done when

1. SNDK row applied, SNDK reselected, `split_horizon_fresh` reads clean for `SNDK|5m`, the 6449933f flag marked reviewed (`ops_restatement_review`).
2. The base rate is measured and recorded here. If it is more than about one a month, a nightly step proposes the row file from the Alpaca corporate-actions feed for the flagged name (proposal only; the apply and the review stay manual, the same rule as `calendar_market`). If it is lower, close this todo with the number and keep the manual procedure in `docs/reference/gotchas.md`.

## Not blocking

No corpus compute runs before the data gate; the stage 2 chain does not touch SNDK's recent bars.
