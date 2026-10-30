---
status: pending
priority: P1
filed: 2026-10-30
source: data lane, intraday slot_coverage recount (53 names still below 0.995 after the calendar and listing_end fixes)
---

# A vendor answer that adds nothing leaves no coverage evidence

`slot_coverage` credits a slot only when a stored bar, an IBKR request window (corroborated by a
stored row) or an applied Alpaca `ohlcv_load` range covers it. Three gaps in that evidence remain,
and they are the whole residue of the intraday failures (53 of 1,529 names, down from 120):

1. An Alpaca nightly request that answers `bars` but returns nothing new writes no `ohlcv_load`
   row, so the empty tail of a halted or delisted name reads as unanswered. `ohlcv_request` holds
   the answer (source `alpaca`, route `SIP`, window start and end, from 2026-10-26) and the audit
   and the gap planner both ignore it. MSGS: nightly windows ending 10-27 to 10-30 returned the
   10-26 session only (248, 162, 82, 82 bars), so 10-27..10-29 were answered empty.
2. Pre-2016 rows from the legacy import have no request ledger. 54 of the 56 names that failed
   after the calendar fix have no pre-2016 IBKR 5m request, so those slots are unasked, not known
   holes. The P0 pre-2016 backfill and the gap-fill lane clear them as they reach each name.
3. A name that left the exchange needs a recorded `listing_end_current` row (CCO, WBD, QRVO have
   one). BZH (merger closed 2026-10-20, NYSE Form 25-NSE) and ACVA (Copart closed 2026-10-16) end in
   the data with no row. PSKY is todo 519.

Fix 1 where the evidence is defined, not in the audit alone: the planner (`gap_plan.py`) and the
audit must read one definition of "answered", or the fetcher re-asks slots the audit already
credits. Count Alpaca `ohlcv_request` windows (outcome `bars` corroborated by a stored row, or
`no_data`) next to applied loads, honoring `partial_bars`. Fix 3 by recording the rows from EDGAR
evidence, one writer, not by editing instruments. Item 2 needs no code.

Not a per-name task: no name is repaired by hand, the mechanism is.
