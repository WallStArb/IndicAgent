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

## Done when

The owner's choice is recorded in 189-10-TASK2-SUMMARY.md's "What follows"; if option 1, the probe's
numbers are recorded there first; 189-11's plan reflects the decision.
