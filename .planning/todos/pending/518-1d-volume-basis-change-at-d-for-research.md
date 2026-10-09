---
status: pending
priority: P2
filed: 2026-10-08
source: plan 185-48 (residual risk of the 1d primary swap; 185-46 review amendment item 2, docs/research/1d-primary-swap-evidence.md "Volume basis (R5)")
owner: the research lane (phase 183 session), with todo 501
---

# Canonical 1d volume changes basis at D = 2026-10-07 for every name

## What

From D the canonical 1d bar of every name is IBKR SMART TRADES; before D it is Tradier for most
names. IBKR SMART counts less volume than Tradier: over the last 250 common sessions the per-name
median IBKR/Tradier ratio has p10 0.409, p50 0.528, p90 0.807 (1,528 names, measured 2026-10-08,
recorded in the evidence of the 1d default row opened by migration 456). So canonical 1d volume
drops at D to about half its earlier level, by a different factor per name: a level change and a
cross-sectional change on one date. Prices are not affected.

Readers hit by it (the consumer list is in the evidence doc): the research panel's volume field and
`research/legs.py`, every trailing-window volume feature (`features/kernels/volume.py`: rel_volume,
volume_z, dollar_vol_z, vol_trend_ratio, vol_range_ratio, CMF; `kernels/smc.py`;
`kernels/calendar.py`), which drop for one window length after D and re-center, and a cross-sectional
volume rank, which shifts by each name's own ratio. The 186-26 rebuild computes these features over D.

## Work

- The S0 data-quality labels mark D as a volume basis change: the date is the `basis_change_date` in
  the evidence of the open 1d default `bar_source_policy` row, read as of the snapshot's
  `policy_as_of` (todo 501 pins it), never a constant in code.
- A spec that reads volume over a window spanning D either declares it (and its statistic is judged
  per side of D) or is refused by a guard; pick one and write it into the S0 hand-off.
- Decide whether volume features in the 186-26 rebuild are masked for one window length after D or
  computed through it with the label; record the decision in the research ledger, not here.

## Gate

With todo 501, before any daily attempt reads volume across D and before 186-26's volume features
are relied on. Volume is never rescaled or spliced (design section 2).

## Done when

- The snapshot manifest carries the volume basis change date for every 1d name and the research
  runner refuses or labels a volume read across it.
- A test pins that the date is read from the policy row as of `policy_as_of`.
