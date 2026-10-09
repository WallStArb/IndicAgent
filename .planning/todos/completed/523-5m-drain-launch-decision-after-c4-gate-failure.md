---
status: resolved
priority: P1
filed: 2026-10-09
resolved: 2026-10-09
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

## Refinement 2026-10-09 (indicagent-87): the tail drain may have no consumer

With 2016+ owned by Alpaca, an IBKR tail drain's only unique product is 2006-2015 5m, and no
research spec currently consumes it. The fallback therefore shrinks from an 18-19-day batch to a
per-name, on-demand fetch targeted at a spec that names its need, the same test the Yahoo deep
archive failed (fetch nobody consumes). Launch order: todo 521 first; the batch tail drain stays
closed unless a spec names the depth it needs.

## Done when

The owner's choice is recorded in 189-10-TASK2-SUMMARY.md's "What follows"; if option 1, the probe's
numbers are recorded there first; 189-11's plan reflects the decision.

## Resolution 2026-10-09

Owner ruled (relayed by indicagent-87, the Alpaca workstream session): todo 521 is green-lit.
The IBKR tail drain stays closed; IBKR depth is per-name on-demand pending a named consumer.
This todo's decision is made; the guardrail (the pilot's u = 38 gap-patch behavior must never
reach the nightly update lane) carries into 521's depth-build plan and 189-11 if it is ever
resumed.

## Reversal 2026-10-09, later: owner ordered the full-depth campaign ("get it all")

After the Alpaca green-light the owner ordered full-depth IBKR 5m for all names anyway ("we want
to get the data from 2006-2016 asap", then "then we want to get it all"). The C4 gate closed as a
research-readiness path; as a completeness campaign it no longer gates anything (Alpaca carries
research readiness), so the owner's order reopens it. Fetcher service and timer re-enabled
2026-10-09 ~18:40 UTC; the queue's SLA band keeps the nightly 1d update lane preempting the drain.
CORRECTION 2026-10-09 (late): the "163 invisible head gaps / hold the phase 2 load" claim was
wrong — a dry-run verification showed the queue already plans heads via proven-days (deepest
stored series, 1d) plus provider floors; the mass of "gaps" was the 1d vendor floor (2000-01-03)
versus the 5m vendor floor (2006-07), not missing data, and only 10 names (ODFL, AAP, IEF, SHY,
TLT, CSX, AMD, EDV, LIN, NTR) have genuine short heads, already queued. The phase 2 canonical
hold is lifted on this correction (coordination to indicagent-87); the drain runs regardless.
Surviving small item: todo 526, per-TF provider-head granularity.
