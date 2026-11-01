---
status: closed
priority: P2
filed: 2026-09-25
closed: 2026-11-01
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

## Landed (research lane, 2026-11-01, commit d7799ca19)

The second writer is deleted. `universe_expansion_stratified_sourcing.py` is draw-only: `_run_commit`,
`_gateway_preflight`, `load_classifications`, the `--commit`/`--classification-csv` arguments, the
gateway-probe client id and the sample tags are gone, and the async entry is a sync draw (`_draw_main`).
The onboarding SOP's "second writer" warning is replaced by the resolution note. The pilot-draw script
the todo names does not exist (the draw successor, `universe_expansion_holdings_draw.py`, imports only
the sampling helpers, which stay). The provider-leaf boundary allow-list drops the script's entry (its
only leaf use was the deleted commit path). Tests: the commit-mode and classification-CSV tests went with
the subject; the 14 draw tests pass, `--commit` now exits 2 as an unrecognized argument.

Closed 2026-11-01: the second writer is deleted (commit d7799ca19). The todo's named
pilot-draw script no longer exists; the draw successor universe_expansion_holdings_draw.py
imports only the sampling helpers, which stay. The deleted commit path was the script's only
IBKR-leaf use, so its provider-leaf boundary allow-list entry dropped with it. The onboarding
SOP records the resolution.
