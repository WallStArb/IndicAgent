---
status: pending
priority: P2
filed: 2026-11-13
source: A8's review of d2-v6 over the switch-plan shapes (a8-daily-rule-switch-plan, landed 2026-11-13)
---

# d2-v6 records no unserved_primary for a session whose only raw answer is a dropped zero-volume placeholder

## What

d2-v6 drops a zero-volume Alpaca observation before the session axis is built, so a session whose
only raw answer is the dropped placeholder leaves the axis entirely: no bar (correct under
`no_fill`) and no `unserved_primary` record. Pre-existing behavior, identical under the live
policy when IBKR does not answer, outcome-neutral for D1 counts.

## What to do

Decide after the 186-26 rebuild (no stored-output-moving d2-v6 change before it): either the
daily stage counts dropped-placeholder-only sessions as a labelled class in its run report
(observability only), or accept and document the class. The C6 gate reads `unserved_primary` and
explains it; today this class is invisible to that read.
