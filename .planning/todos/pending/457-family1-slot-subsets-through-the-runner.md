---
status: pending
priority: P2
filed: 2026-09-29
source: family 1 iterations 1-3 (2026-09-29): exploration outside the runner
---

# Run the family 1 open and close slot subsets through the runner so they are counted

## What

Family 1 iterations 2 and 3 ran outside the runner (`scripts/research/family1_slot_profile.py`,
`family1_conviction_gating.py`, `family1_liquid_close.py`): a per-slot split, the opening and
closing slots alone (replicated on 201 names outside the original 233), a 30-cell conviction
grid and a 32-cell liquid-close grid. Under E18 every real-vintage series a person can see joins
the selection universe, and these are not in it. The runner has no slot-subset trade mask or
gated construction (phase 187 `ConstructionRule`; todo 442 item 2 requires the E17 H0 battery
to cover it first).

## Steps

1. After phase 187: add a slot-subset trade mask and the `keep` gate as a construction, with the
   E17 H0 battery (todo 442).
2. Rerun the opening slot, the closing slot and open plus close at keep 0.5 and 0.1 on the
   233 names, and the same on the 201-name set, in `exploration` mode so each series and its
   full return series are recorded.
3. Record the outside-the-runner looks in the ledger's disclosure for the selection set.

## Notes

Cost is a promotion gate, not a discovery gate (E18): the edge results stand. Measured cost:
`docs/research/family1-spread-sample-2026-09-29.csv`.
