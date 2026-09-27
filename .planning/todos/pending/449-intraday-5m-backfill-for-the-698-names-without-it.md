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

Fetch 5m, 15m and 1h (owner decision, 2026-09-27). Phase 185 D2b still derives the 15m and 1h
readers see from 5m on session-anchored edges (todo 446); the fetched IBKR 15m and 1h are kept as
raw observations and are the independent check on that derivation (185-12 parity check). They
cost little: IBKR chunks are 730 days (15m) and 1095 days (1h) against 150 days for 5m.

Running since 2026-09-27: 5m lanes on clients 40-43 (`logs/backfill_ops/intraday_5m/`), 15m+1h
lanes on clients 46-48 (`logs/backfill_ops/intraday_htf/`, `intraday_htf_lane.sh`). The phase 186
rebuild gates on the 5m part only, since it reads derived 15m/1h.

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

5m, 15m and 1h coverage per name matches its expected span (first available bar to today), provider-empty
spans are recorded in `ohlcv_empty_history`, and the names are promoted per the SOP. The coverage
query and its output are recorded here.
