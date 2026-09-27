---
status: pending
priority: P1
filed: 2026-09-26
source: owner, phase 186 planning (2026-09-26): the feature_vectors rebuild is multiday and runs once, on full bar history
---

# Backfill 5m bars for the 698 names without intraday history

## What

The universe has 931 `compute_eligible_1d` names but only 233 `compute_eligible` (intraday)
names. 1d history exists for all 931; 5m does not exist for the other 698. The phase 186
`feature_vectors` rebuild covers all 931 names and cannot start until this backfill is complete
(186-CONTEXT D-32).

Only 5m needs fetching: phase 185 D2b derives 15m and 1h from 5m on session-anchored edges
(todo 446), so stored IBKR 15m and 1h are raw observations only.

## Constraints

- Follow `docs/foundation/instrument-onboarding-sop.md` (backfill, verify, promote
  `compute_eligible`); never hand-write `instruments`.
- SMART-routed intraday history starts at a name's last listing-venue move (todo 433, phase 185
  D3). The backfill records where each name's history starts and why, so D3's recovery can fill
  the gap later through content-digest keys.
- IBKR pacing and client-id limits (`_MAX_CLIENT_ID=50`); check for other running backfills
  first.
- Measure a pilot (for example 10 names) for wall-clock time and rows before launching the rest,
  and state the expected duration.

## Done when

5m coverage per name matches its expected span (first available bar to today), provider-empty
spans are recorded in `ohlcv_empty_history`, and the names are promoted per the SOP. The coverage
query and its output are recorded here.
