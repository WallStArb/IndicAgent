---
status: pending
priority: P3
filed: 2026-09-29
source: family 1 iteration 3 (2026-09-29): standalone book does not clear measured cost
---

# Test the family 1 slot alpha as an execution-timing overlay on a slower book

## What

Family 1's same-slot alpha (opening and closing half hours strongest) does not clear measured
cost as a standalone book (`docs/plans/2026-09-29-family1-iteration-3-open-close-slots.md`,
questions 3 and 4). Hypothesis, untested: use the alpha to choose when to enter or exit trades
a slower strategy already makes (family 9, daily, multi-day), which pays no incremental spread
because the trades happen anyway. The gain would be edge per unit traded that the slower book
captures at its own turnover.

## Steps

1. Wait for a slower book with a recorded trade list (family 9 or a daily construction).
2. Pre-register: slot-alpha-timed entries versus entry at a fixed time, same trades, paired by
   session; readout in bp per trade, criteria stated before any number.
3. Counts as a look in the selection universe.

## Also open from iteration 3

Full 13-slot profile on the 201 names (only open, close and all were run there); BRK.B does not
resolve in the IBKR spread sample (IBKR wants "BRK B").
