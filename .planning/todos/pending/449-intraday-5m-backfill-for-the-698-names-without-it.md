---
status: pending
priority: P1
filed: 2026-09-26
source: owner, phase 186 planning (2026-09-26): the feature_vectors rebuild is multiday and runs once, on full bar history
---

# Backfill raw 5m bars for the 698 names without intraday history (5m only)

## What

The universe has 931 `compute_eligible_1d` names but only 233 `compute_eligible` (intraday)
names. 1d history exists for all 931; 5m does not exist for the other 698. The phase 186
`feature_vectors` rebuild covers all 931 names and cannot start until this backfill is complete
(186-CONTEXT D-32).

Scope decision (owner, 2026-10-06, replaces the 2026-09-27 "fetch 5m, 15m and 1h" decision): fetch raw 5m only.
Research features need 5m through 1d on every name, and 15m and 1h are derived from 5m (phase 185 D2b, todo 446;
docs/plans/2026-09-29-intraday-bar-store-redesign.md) so every timeframe a feature sees comes from the same bars.
Fetching 15m and 1h from IBKR as well costs the single history stream days that 5m needs. Which names get 5m:
all 931 `compute_eligible_1d` names (the 698 missing 5m plus the 233 that have it); the rebuild's scope is the
promoted set, chosen by promotion state and never by screening on history or returns. The 598 active names that are
not yet promoted are outside this todo until the SOP promotes them.

State 2026-10-06 (measured): IBKR 15m/1h vendor bars were fetched for 296 names that have no 5m; they stay as raw
data and as the parity check against derived bars, and they are not deleted before that name's 5m lands and its
derived 15m/1h pass parity. The old chain (`intraday_chain.sh`) is stopped; the phase 189 fetcher
(`indicagent-ibkr-history-fetcher`) is stopped until its queue is 5m only. The `PAUSE_5M` marker is a leftover of
todo 462, whose blocker (the synthetic fill) ended with the 185-25 real-rows swap. IBKR serves one heavy history
stream at a time; 5m chunks are 150 days (about 49 requests for 20 years) under 58 requests per 10 minutes.

## Constraints

- Follow `docs/foundation/instrument-onboarding-sop.md` (backfill, verify, promote
  `compute_eligible`); never hand-write `instruments`.
- SMART-routed intraday history starts at a name's last listing-venue move (todo 433, phase 185
  D3). The backfill records where each name's history starts and why, so D3's recovery can fill
  the gap later through content-digest keys.
- IBKR pacing and client-id limits (`_MAX_CLIENT_ID=50`); check for other running backfills
  first.
- Measure a pilot (for example 10 names, 5m only) for wall-clock time and rows before launching the rest,
  and state the expected duration.

## Done when

5m coverage per name matches its expected span (first available bar to today), provider-empty
spans are recorded in `ohlcv_empty_history`, and the names are promoted per the SOP. The coverage
query and its output are recorded here.

## Stream lease (2026-09-27)

Phase 185 plan 09 adds one IBKR history-stream lease (185 CONTEXT D-29) and restarts this chain's pipeline process onto it: the chain runs at bulk tier and yields at each (symbol, tf) unit to the nightly and to 185's campaigns, and the nightly stops skipping while it runs. Plan 12 restarts it again so its 15m/1h writes go to the raw archive. The chain keeps clients 46 and 40.
