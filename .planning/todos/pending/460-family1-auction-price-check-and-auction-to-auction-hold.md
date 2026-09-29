---
status: pending
priority: P2
filed: 2026-09-29
source: family 1 iteration 4 (2026-09-29): the edge sits at the two auction prints
---

# Family 1: verify the stored open and close are auction prices, then test an auction-to-auction hold

## What

Iteration 4 (`docs/plans/2026-09-29-family1-iteration-4-5m-timing.md`) found the opening slot's
P&L is all earned by 09:35 (a move away from the 09:30 print) and 59% to 69% of the closing
slot's after 15:50 (a move into the closing print). Two open questions follow, in order.

1. Are the stored 09:30 open and closing prices official auction prices a market-on-open or
   market-on-close order would get? About two thirds of the open-plus-close book's gross depends
   on the open print being tradable. The 1d open equals the 5m 09:30 open on 99.95% of
   name-days (2024 to 2025), which shows the two agree, not that either is the auction price.
2. Does the opening-slot edge hold to the close? An opening-auction-to-closing-auction hold pays
   no half-spread on either leg. Opening-slot E at 11:00 is still about 1.0 bp per unit at keep
   0.1 (iteration 4); iteration 1's full-session horizon (E 0.02 at h26) averaged all slots and
   does not answer this for the open slot alone.

## Steps

1. Auction price check: for a sample of names and sessions, compare the stored open and close to
   IBKR's official open and close (`ADJUSTED_LAST`/`TRADES` 1d open and close are consolidated
   auction prices where available; otherwise the primary listing exchange's auction print) and to
   the first and last quote midpoints. Report the gap in bp per name group. If the stored open is a
   first trade printed away from the midpoint, restate iteration 3 and 4's opening-slot numbers on
   a tradable price before anything else.
2. Pre-register the hold in the iteration 4 note or a new one: entry at the 09:30 open, exit at
   the close (extend the 5m curve to 16:00 for the opening slot's weights), keep 0.1, both
   members; criteria for E, net E at zero spread on both legs plus the measured auction cost
   assumption, and the risk of the idle hours, stated before the curve is read. One counted look.
3. If it passes on the 233 names, confirm on the 201 replication names once their 5m history
   lands (todo 449), then the forward span once.

## Related

Todo 457 (rerun the slot subsets through the runner so they are counted), todo 458 (overlay
route, the alternative if the hold fails).
