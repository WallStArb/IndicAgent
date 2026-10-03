---
status: pending
priority: P3
filed: 2026-10-03
source: interactive session (universe wave 2 review)
---

# Price bars have one source: add a sampled cross-check

## What

Dividends cross-check Yahoo against IBKR; prices are IBKR only. The corrupt-print scan catches
isolated bad bars but not a systematic problem (a stale venue, a wrong adjustment) that is
self-consistent.

## Fix

A read-only report comparing a fixed random sample of names' daily closes against Yahoo, with the
sample drawn by seed from APR and the divergence tolerance an APR key. Output: per-name max and
median relative difference, listed in the batch README entry at SOP stage 8. No second price writer.
