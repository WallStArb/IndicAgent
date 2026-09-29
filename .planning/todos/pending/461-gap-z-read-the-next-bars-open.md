---
status: pending
priority: P1
filed: 2026-09-29
source: plan 186-12 causality probe on the moved gap_z kernel
---

# gap_z at bar T included bar T+1's open (one-bar lookahead); traced dependents need a re-look

## What

The causality probe (186-12) failed the moved `gap_z` kernel. `_gap_z_series_full` wrote the
z-score of the gap at bar k+1 into row k, so the stored `gap_z` at bar T was built from
`open[T+1]`, and the last row of every batch stayed 0.0 (every live `compute()` call too, since
the live call is the last row of its window). All timeframes, 1d included.

Code fixed in plan 186-12 (failing test first: row 300 moved from -1.935 to 1.105 when bar 301's
open changed). The golden fixture was regenerated for `gap_z` only. Stored `feature_vectors` rows
carry the defect until the phase 186 rebuild (186-26).

## Dependents to re-look (read only, 2026-09-29)

- `docs/research/construction-verdict-ledger.md` lines 155-169: the per-feature IC read of
  `gap_z` ("95/232 broad support", "strongly negative intraday") was measured on the leaky column.
  A gap between the close of T and the open of T+1 followed by the open-to-open label that starts
  at open[T+1] is exactly the mean-reversion pattern that reading found, so the intraday effect is
  likely the leak, not a bar-to-bar gap effect. Re-measure on rebuilt rows before Family 2 uses it.
- `docs/research/summary-cards/legacy-n1-nonlinear-interaction-combiner.md`: fold 1 breaches G1 on
  `gap_z` (0.248, 0.210) "even at colsample 0.05"; a leaking column dominating a fold fits that.

Neither doc was edited in plan 186-12 (research-lane files); annotate both when this is picked up.

## Fix status

Code: done (186-12). Open: annotate the two dependents, re-measure `gap_z` on the rebuilt matrix,
add the defect to the `cache-feature-vectors-v1` card (done in 186-12) and confirm the rebuild
drift report (186-27) shows `gap_z` moving.
