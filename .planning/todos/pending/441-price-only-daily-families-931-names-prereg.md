---
status: pending
priority: P1
filed: 2026-09-26
source: adopted unified design (todo 436), section 6 attempts 3-4; Fable review item 14
---

# Pre-register the price-only families on the 931 names: residual and industry momentum, sector lead-lag

## What

The shortest path to a tradeable verdict runs on data that needs no feature pipeline. Alongside
todo 423 (residual short-term reversal on the names the 2026-09-13 screen never saw), pre-register:

1. Residual momentum (12-1 month on S1 residual returns) and industry momentum (SCH industry
   groups), daily, on the 931 names.
2. Sector-ETF-leads-constituent lead-lag at 5m or 15m (ledger family 3), sectors from SCH,
   restricted to constituents with intraday bars.

Each spec states its universe as of t, carries phase 185 D0's labels (the survivorship bound was retired by the owner 2026-10-09, todo 514) and a
delisting-return sensitivity, and declares its costed construction for promotion (E18).

## Done when

Specs are registered and run as attempts 3 and 4.

## Dividends (todo 428, closed 2026-09-26)

A daily-clock spec declares `panel.total_return: {suspect_yield: <x>}`. Price-only daily returns
carry every ex-dividend drop as a loss, which biases daily targets and can manufacture
price-level signals on high-yield names. See `research/dividends.py`; state the suspect_yield
(0.10 is the value the reference checks used) in the pre-registration.
