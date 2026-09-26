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

`universe_expansion_onboard_manifest.py` already does this (qualify every row outside any
transaction with a gateway probe before and after, then one short write transaction) and is
the documented onboarding path (CLAUDE.md, `config/universe/README.md`); it onboarded all 659
names on 2026-09-26. The remaining defect is the second writer: delete `_run_commit` and the
`--commit` path from `universe_expansion_stratified_sourcing.py` and from
`universe_expansion_pilot_draw.py`, which imports it, so draw scripts only draw and write a
manifest. Keep the sampling helpers `universe_expansion_holdings_draw.py` imports.
