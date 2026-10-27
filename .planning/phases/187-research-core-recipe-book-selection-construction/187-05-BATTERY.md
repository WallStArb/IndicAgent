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

## Pass 3 pending (2026-10-27): plus-one adjusted p-values

A Codex review found the adjusted p-values were the plain share of draws, k / reps; they are
now (k + 1) / (reps + 1), the finite-bootstrap form that never rejects above nominal. Every
number above was computed under k / reps, so the full run below uses the new form. The record
it writes carries `complete` and `stepm_sha256`; `select_books.py --battery` accepts it as its
attestation only when it covers every cell, holds in every gating cell, and matches the StepM
code and the APR's fwer and block mean. An AGY review then found that a draw landing on
fewer than two of an attempt's sessions scored -inf, dropping it from the max and lowering
p-values for short spans; such a draw now scores +inf (conservative). The full run uses both
changes.

## Pass 3 (2026-10-27): the full battery on the reviewed code

Per-draw studentization, plus-one p-values, +inf for a draw without evidence; 1,000 simulations
per cell, 500 draws, block mean 20 (`logs/research/stepm_null_battery_20261027.json`).

| Cell | Gate | Rejections / bound |
|---|---|---|
| gaussian | gate | 55 / 67 |
| t4 | gate | 62 / 67 |
| vol_clustering | gate | 63 / 67 |
| factor | gate | 62 / 67 |
| static_cell_means | gate | 54 / 67 |
| slot_effects | gate | **71 / 67 (fails)** |
| late_listings | gate | 54 / 67 |
| hostile | gate | 39 / 67 |
| real_grid_hostile | gate | **70 / 67 (fails)** |
| s1_hostile | gate | 53 / 67 |
| static_vol_stress | diag | 87 / 67 |
| hostile_stress | diag | 65 / 67 |
| s1_slot_stress | diag | 787 / 67 |

Verdict: FWER fails in two gating cells; selection stays refused (`select_books --battery`
rejects this record). The pass 2 probe's 52 in slot_effects was a different seed draw (the driver
seeds by cell position, and the probe ran three cells), not a repair: 52 and 71 are both within
sampling error of a true rate near 0.06.

Reading: the excess is spread across cells (0.054 to 0.071), not one mechanism, which points
at the E17 statistic StepM studentizes, not at StepM. E17's own battery found single tests
about 1.4 times nominal at 0.00167 on these short 1,500-session panels, falling to about 1.1
times at the real length of 4,000 sessions, and family 2's combined cell about 7 to 8 percent at
0.05. Diagnostic running: the two failing cells at 4,000 sessions with fresh seeds
(`logs/research/stepm_null_battery_length4000_20261027.json`). If they hold there, the decision
whether the gate is judged at the real panel length is the owner's, as E17's criterion was.

## Open

The full 13-cell battery under studentize="draw" was started and then stopped by the session's
memory reaper before any cell was saved (the driver now appends each finished cell to
`<out>.partial.jsonl`). It must rerun and hold in every gating cell before any selection
set from `select_books.py` (plan 06, landed) counts as a result. The diagnostic cells document known E17 limits and do not gate.
