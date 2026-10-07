---
status: pending
priority: P1
filed: 2026-10-07
source: 185-46 Task 2, rule R4 of docs/research/1d-primary-swap-evidence.md
owner: phase 189 fetcher (189-10)
---

# The nightly update lane exceeds R4's 120 minutes; measure the 5m pacing ceiling

## What

R4 (pre-registered in docs/research/1d-primary-swap-evidence.md) bounds the nightly update lane, one
short request per name for 1d and for 5m, at 120 minutes (half of infra.backfill.run_budget_minutes).
Measured 2026-10-07 it fails in every case: 130 minutes today (1d 90 at the fetcher's serial bound of
2.0 s pause plus 1.54 s latency, 5m 40 for 233 names) and 349 minutes once every compute_1d name holds
5m (5m 259 for 1,502 names). The 5m slice dominates because 5m is paced by the default limiter,
infra.ibkr.rate_limit_max_requests 58 per infra.ibkr.rate_limit_window_sec 600 (348 an hour), not by
a measured figure. It also lengthens the 5m drain: 189-10 Task 2's 10.6-day floor becomes about 12.7
days and its 12 to 18 day expectation about 14.4 to 21.6 days.

src/providers/ibkr.py records that IBKR's hard pacing rule binds bars of 30 seconds or less and that
bars of a minute or more meet only a soft slowdown; 1d already runs at its own measured 200 per 600 s.
5m has never been measured.

## Fix

Measure first: run `scripts/infrastructure/backfill/infrastructure_ibkr_chunk_and_rate_limit_probe.py
--rate-timeframe 5m --rate-ceilings ...` with short (update-lane) spans and record the ceiling and the pushback count.
If it holds above 58 per 600 s, set `infra.ibkr.rate_limit_max_requests_by_tf` 5m through a migration
with provenance [rca_analysis] and the probe output as evidence, then recompute the nightly cost with
`scripts/research/swap_1d_primary_measure.py --rate`. If it does not, the update lane needs a
cheaper 5m shape (for example the 5m update only for names whose 1d bar for the session exists, or a
5m update every second night with the overlap widened to match), decided with the numbers.

## Gate

Before 189-10 Task 2's pilot criterion is judged (its extrapolation deducts this slice), and before
189-10 Task 3 launches the timer.

## Done when

- the 5m ceiling is measured and recorded, the APR value set or left with the reason
- the update-lane cost is remeasured and is at most 120 minutes, or the owner accepts the figure in
  writing in the evidence doc
