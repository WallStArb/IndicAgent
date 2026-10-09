---
status: pending
priority: P1
filed: 2026-10-09
source: 189-10 Task 2 pilot results (b3e46fa4f); owner decision required
---

# 5m drain launch decision: the C4 gate failed on measured latency, not on limits

## What

The pre-registered launch gate (D_proj at most 18 days) measured 37.3 days. Root cause: a 150-day
5m depth request takes about 40 s, so the drain paces at about 88 requests/hour, a quarter of the
L5 = 348/h limiter ceiling the design's 12-18 day expectation assumed. No limit change inside the
current design closes that. The owner chooses between:

1. Wider chunks per request (fewer, larger requests) if IBKR serves them at similar latency; needs
   one wide-chunk latency probe (not run by the pilot; run it under the FetcherLock before deciding).
2. Accepting a 30-40 day drain in a dedicated lane with its own bound (189-11's B_drain mechanism
   already anticipates this).

Guardrail carried from the pilot: the measured tail behavior (u = 38 requests per tail name, ledger
gap patches) must never reach the nightly update lane; the design tail is one request per name.

## Probe result 2026-10-09 (option 1 is dead)

The wide-ask probe (SPY 5m, one request per width, under the FetcherLock, nothing stored): 150d OK
11,663 bars 18.7 s; 180d OK 14,003 bars 48.1 s; 270d, 365d and 730d all FAILED with Error 162
(pacing cancel) and reqHistoricalData timeouts on every retry, 375 s wasted per width, +2 throttles
each. IBKR refuses 5m asks beyond roughly 180 days; the current 150-day chunking is at the ceiling.
What remains is the 37-day drain as measured, or not running the IBKR drain at all for the span a
second tape covers (Alpaca serves complete 5m from 2016-01-01; see indicagent-87's pilot
`docs/plans/2026-10-09-alpaca-integration-pilot.md` and admission path todo 521). The IBKR drain's
remaining unique value is the 2006-2015 tail and a second tape for parity.

## Done when

The owner's choice is recorded in 189-10-TASK2-SUMMARY.md's "What follows"; if option 1, the probe's
numbers are recorded there first; 189-11's plan reflects the decision.
