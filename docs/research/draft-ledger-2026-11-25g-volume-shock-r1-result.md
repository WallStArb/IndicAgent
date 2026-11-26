## 2026-11-25g: R-1 read for `volume_shock_1_50` (lead record, DRAFT)

Read once on 2026-11-25 under the declaration of 2026-11-25f, with the one declared command and no other arguments: `.venv/bin/python scripts/research/replication_subperiods.py --run-groups c7abcf52 4f4a4148 --member volume_shock_1_50` (exit 0, `scripts/research/replication_subperiods.py` unchanged). Non-independent (same dates, core names a subset of primary), non-gating, no look charged (vintage_1 stays at 24 charged rows of budget_m 30), nothing promoted or removed. The t is the descriptive HAC t of the stored D_s over the cell, not the run's decision statistic. No cell holds a non-finite session.

| Panel | Sub-period | Sessions | Mean session P&L | t | One-sided p |
|---|---|---|---|---|---|
| primary (c7abcf52, spec 597a275c) | 2007-03-01 to 2011-12-31 (scored from 2008-02-29) | 969 | +1.433e-04 | 2.01 | 0.0223 |
| primary | 2012-01-01 to 2018-12-31 | 1,760 | +6.330e-05 | 2.97 | 0.0015 |
| primary | 2019-01-01 to 2025-12-23 | 1,755 | +3.226e-07 | 0.02 | 0.4924 |
| core (4f4a4148, spec 7d4dbf49) | 2007-03-01 to 2011-12-31 (scored from 2008-02-29) | 969 | +1.144e-04 | 1.33 | 0.0919 |
| core | 2012-01-01 to 2018-12-31 | 1,760 | +2.104e-05 | 0.58 | 0.2794 |
| core | 2019-01-01 to 2025-12-23 | 1,755 | -1.713e-05 | -0.34 | 0.6313 |

Non-positive cells: 1 of 6 (core, 2019-01-01 to 2025-12-23). Per declaration item 5 it is disclosed and goes to the forward power plan as a haircut; it does not remove `volume_shock_1_50` from the selection or from a book.

Read of the power note (declared 2026-11-25f item 6: about 1.39, 1.88 and 1.88 from the stored primary t 3.00). Primary: 2.01 is above its 1.39, 2.97 is above its 1.88, and 0.02 is far below its 1.88; the primary mean falls from 1.433e-04 to 3.2e-07, essentially zero (technically positive, so the cell is not counted as non-positive), a steeper fall than the `reversal_21` primary of 2026-11-23c (8.70e-04 to 5.85e-05, last t 0.36). The pooled primary result (adjusted p 0.0325) rests mostly on the first two sub-periods. Core: the declared expectation was built from the primary t; the same arithmetic on the core run-level t 0.81 gives about 0.38, 0.51 and 0.51, and the core cells (1.33, 0.58, -0.34) are above the first two and below the third. The reading is possible decay of the effect, not a verdict, and a descriptive disclosure of series already charged.

Consequence. `volume_shock_1_50` is selected by StepM on primary only (2026-11-25b), has no core replication on the panel level, and shows no effect in the last seven years on either panel. Together with the 547 hold (family 10 reads S1 vintage_1), it is not a book candidate before the forward power plan carries the 2019 to 2025 cells as the haircut input. Every look stays counted; this entry adds none.

Numbers and sources. All cells: the output of the command above (one rerun with identical arguments, made to check reproducibility, was byte-identical; no other arguments were tried). Expected sub-period t: 3.00 times the square root of 969/4,484, 1,760/4,484 and 1,755/4,484; core 0.81 times the same ratios (`decision_t` of runs 07d6dfc3 and 11f2076f). `reversal_21` comparison cells: ledger 2026-11-23c. Charged rows: ledger 2026-11-25b.
