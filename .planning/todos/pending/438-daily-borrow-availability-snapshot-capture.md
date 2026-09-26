---
status: pending
priority: P1
filed: 2026-09-26
source: adopted unified design (todo 436), section 9.3
---

# Record daily short-borrow availability and fee for the full universe

## What

A market-neutral book that shorts unborrowable names is not the object that will trade, and IBKR
serves borrow availability (shortable shares, fee rate) live only: no history can be bought. Start
a daily snapshot now for every active instrument, so any forward span has real borrow data and the
construction rule can enforce availability as a hard constraint (phase 188).

Same pattern as phase 185 D8's dated holdings snapshots: one writer, append-only, dated rows,
through `src/providers/ibkr.py`. Timer enabled, with a completion metric.

## Done when

Snapshots accrue daily for the full universe and a missed day is heard, not silent.
