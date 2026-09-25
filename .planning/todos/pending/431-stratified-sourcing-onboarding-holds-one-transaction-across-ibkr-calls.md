---
status: pending
priority: P2
filed: 2026-09-25
source: phase 182 code review (finding 5)
---

# Stratified-sourcing onboarding holds one DB transaction across hundreds of IBKR calls

## What

`scripts/infrastructure/universe_expansion_stratified_sourcing.py` opens one outer transaction
and calls `onboard_instrument()` per symbol inside it, each making an IBKR qualify call with a
30s timeout. For N in the hundreds the transaction stays open for hours:

- It holds row locks on `instruments`, `instrument_classification` and `backfill_status`,
  blocking the nightly backfill's `backfill_status` writes.
- A mid-run gateway logout (the weekly 2FA logout, todo 395) turns every remaining qualify into
  `False`, counted as rejections, and the partial batch commits as a successful run.
- A run crossing UTC midnight is now refused loudly by migration 368's same-day write guard
  (before 368 it would have backdated rows).

## Fix

Qualify every symbol first, outside any transaction, and abort the run if the rejection rate
spikes (a gateway problem, not a real rejection). Then open one short write transaction for the
qualified set. Keep per-symbol savepoints so one bad row does not sink the batch.
