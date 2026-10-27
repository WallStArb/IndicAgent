# 187-05: StepM through the E17 H0 battery

Driver: `scripts/research/stepm_null_battery.py` (1,000 simulations per cell, 500 bootstrap
draws, mean block 20 sessions, family-wise 0.05, size bound the upper 99% binomial quantile:
67 of 1,000). Each simulation's null universe is family 1's four members plus their equal-weight
book on one panel; a family-wise error is any arm selected.

## Pass 1 (2026-10-26): studentize="sample" (every draw scaled by the sample HAC se)

| Cell | Gate | Rejections / bound |
|---|---|---|
| gaussian | gate | 56 / 67 |
| t4 | gate | 63 / 67 |
| vol_clustering | gate | 53 / 67 |
| factor | gate | 65 / 67 |
| static_cell_means | gate | 61 / 67 |
| slot_effects | gate | **74 / 67 (fails)** |
| late_listings | gate | 56 / 67 |
| hostile | gate | 33 / 67 |
| real_grid_hostile | gate | 63 / 67 |
| s1_hostile | gate | 45 / 67 |
| static_vol_stress | diag | 81 / 67 |
| hostile_stress | diag | 63 / 67 |
| s1_slot_stress | diag | 791 / 67 |

Verdict: FWER fails in a gating cell. Selection stays disabled.

## Pass 2 probe (2026-10-26): studentize="draw" (each draw's own HAC se, Romano-Wolf's form)

| Cell | Rejections / bound |
|---|---|
| gaussian | 57 / 67 |
| factor | 63 / 67 |
| slot_effects | 52 / 67 |

Per-draw studentization repairs slot_effects and is now `stepm`'s default. The residual rates
just above 0.05 in gaussian and factor track the E17 per-arm tests' own small excess, within
the bound.

## Open

The full 13-cell battery under studentize="draw" was started and then stopped by the session's
memory reaper before any cell was saved (the driver now appends each finished cell to
`<out>.partial.jsonl`). It must rerun and hold in every gating cell before any selection
set from `select_books.py` (plan 06, landed) counts as a result. The diagnostic cells document known E17 limits and do not gate.
