---
status: pending
priority: P2
filed: 2026-10-09
source: 189-10 Task 2 pilot C8 result (b3e46fa4f); DBMF 2019-10-16, 2021-01-08, 2021-11-04
---

# Mid-history single-day provider gaps: give them a recorded span so C8 can pass

## What

DBMF's slot coverage misses 0.995 on 3 single-day IBKR 5m gaps (2019-10-16 78 slots, the whole
session, the 1d row exists so DBMF traded; 2021-01-08 73; 2021-11-04 7). The days are provider-empty
inside answered chunks, but `ohlcv_empty_history` only records ranges from IBKR definitive
"no data" answers, which the backward walk cannot produce when neighbor chunks return bars. So the
gap is re-requested every run and C8's two allowed explanations never apply.

Extend the empty-history mechanism: a single-day (or short) span with bars present on both sides
inside one answered window is recordable as provider-empty, with the confirming window as evidence.
No bars are deleted or hidden; the record only stops re-requests and lets C8's explanation category
apply.

## Done when

The 3 DBMF days carry a recorded 5m span; C8's slot coverage for DBMF passes or its shortfall is
explained per the registered rule; the mechanism is general (not DBMF-special-cased).
