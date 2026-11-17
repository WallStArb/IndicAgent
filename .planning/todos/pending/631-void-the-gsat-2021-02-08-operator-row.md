---
status: pending
priority: P3
filed: 2026-11-17
source: todo 628 evidence pass (GSAT 2021-02-10 is a real move, not a split)
---

# Void the GSAT 2021-02-08 operator row

## What

`corporate_action_current` holds a todo 592 operator row for GSAT effective 2021-02-08, factor 0.609687, route
`alpaca/sip_rth` (`split_rescale_rows_2026_11_10_b1.csv`). It says Alpaca's series sat at 0.609687 of the correct
level before 2021-02-08 and rescales it. The evidence of 2026-11-17 contradicts it: Alpaca, IBKR and the rescaled
Massive series all move 18.45 (2021-02-08) to 31.2 (2021-02-09) to 36.0 (2021-02-10) with 17 to 300 times normal
volume, the same real move in every vendor (the January and February 2021 squeeze). The row manufactures a step in
Alpaca's own series; it does not touch canonical (Massive serves 2021), but the 2021 Alpaca raw route is rescaled
wrongly for any consumer that reads it (the daily rule's Alpaca route, the Alpaca 5m selection since the route
rescale landed).

## Requirement first (Musk step 1)

Confirm the row is wrong by measuring Alpaca's own close against Yahoo's adjusted close across 2021-02-08 (the
audit's per-series method) before voiding; if the measure reads Alpaca as continuous, void.

## Scope

1. The per-series measurement (read-only).
2. `ops_split_detect --void` with the evidence (the row is append-only; a void row supersedes it).
3. Reselect GSAT 5m and re-derive 1d and the grid for the name (Alpaca series only matters where selected).

## Gates

`split_continuity` for GSAT unchanged; selection `--compare` shows differences only on GSAT; unit suite exit code.
