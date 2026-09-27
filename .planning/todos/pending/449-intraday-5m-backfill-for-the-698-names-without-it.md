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

Status 2026-09-27: IBKR serves one heavy history stream at a time; 4 parallel 5m lanes (plus 3 15m/1h lanes) produced no more throughput than one and mostly timed out (5m done for 4 names in 6 hours). Now one stream: `logs/backfill_ops/intraday_chain.sh` runs 15m+1h for all 698 names first (client 46, `logs/backfill_ops/intraday_htf/`), then 5m (client 40, `logs/backfill_ops/intraday_5m/solo_*`). 15m/1h go first because the strategy families read them and they need about a third of 5m's requests. Solo 5m rate was about 2 minutes per year of history, so 5m is roughly two weeks. The nightly 1d backfill skips while any backfill runs. The phase 186 rebuild gates on the 5m part only, since it reads derived 15m/1h.

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

## Stream lease (2026-09-27)

Phase 185 plan 09 adds one IBKR history-stream lease (185 CONTEXT D-29) and restarts this chain's pipeline process onto it: the chain runs at bulk tier and yields at each (symbol, tf) unit to the nightly and to 185's campaigns, and the nightly stops skipping while it runs. Plan 12 restarts it again so its 15m/1h writes go to the raw archive. The chain keeps clients 46 and 40.
