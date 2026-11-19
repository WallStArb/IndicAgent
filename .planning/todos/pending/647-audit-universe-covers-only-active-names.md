---
status: pending
priority: P2
filed: 2026-11-19
source: lane 2 of the 609 chain, report of indicagent-0a
owner: lead
---

# The reconciliation audit and the daily derivation see only is_active names

## What

`bar_reconciliation_audit` (universe: the `backfill` dimension, `is_active = true`) and the daily derivation timer (`_DISCOVER_DAILY_SYMBOLS_SQL`, the same dimension) never visit the 33,850 inactive instruments added by the stage 2 install, so after the one explicit derivation run nothing audits or refreshes them. The audit took 6,982 s for 1,529 names, so naively widening it does not finish in a night.

## Done when

A decision and a build: a cheaper audit tier for the stage 2 names (counts, session coverage, split continuity on the membership span only) or a sampled audit with a recorded rate, and a derivation path for their later vendor restatements. Until then a recorded caveat says the dead-name history is derived once and unaudited.
