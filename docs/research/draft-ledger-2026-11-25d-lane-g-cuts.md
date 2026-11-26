## 2026-11-25d: the StepM verdict on the three survivors under each todo 547 cut (DRAFT for the lead, not finalized)

No new statistic is computed. The selection read of 2026-11-25b is the only StepM result and it does not depend on the 547 ruling: the universe is every charged attempt of vintage_1 (16 series, 24 charged rows of budget_m 30), whatever is later certified. What 547 changes is use of the result. Both cuts below read the same numbers (StepM t and adjusted p from 2026-11-25b; gross Sharpe, mean session P&L and turnover as stored on the run rows; the run rows' own decision t is 3.09, 3.50, 3.00 and 0.81 for the four rows of the table and is not the t shown).

| Candidate | StepM t | Adjusted p | Gross Sharpe | Mean session P&L | Turnover per session |
|---|---|---|---|---|---|
| reversal_21 primary (737fe892) | 3.46 | 0.0150 | 1.76 | 3.03e-4 | 2 |
| reversal_21 core (1c4ff135) | 3.84 | 0.0050 | 1.81 | 3.64e-4 | 2 |
| volume_shock_1_50 primary (07d6dfc3) | 3.14 | 0.0325 | 1.08 | 5.59e-5 | 2 |
| volume_shock_1_50 core (11f2076f) | not selected | raw p 0.209 | 0.32 | 2.63e-5 | 2 |

Cut A (547 certify the reversal members and book now): reversal_21 is selected on both panels and stays the book candidate. volume_shock_1_50 is selected on primary only.
Cut B (547 option b, the PM decision of 2026-10-31 recorded in todo 547, owner-delegated with the owner veto retained, not a ledger ruling: hold the family): neither daily residual member is certified and no book is built until the rebuilt S1 vintage and a fresh preregistration exist. Family 10 is treated as held on the same basis (lead working position 2026-11-25; the owner decision stays open): its spec reads S1 vintage 1 (`factor_spec: vintage_1`; members are ranks over share volume and S1 residual returns, prereg section 3), so the S1 drift of 547 cause 3 reaches it. The 2026-10-31 text names the daily residual family only; whether family 10 is inside the hold is part of the owner question on 547 (below). The StepM numbers stay recorded either way and the looks stay charged.

Disclosures. (1) The R-1 read of 2026-11-23c (primary last sub-period mean 5.85e-5, t 0.36) is the only sub-period evidence and applies to reversal_21 alone; no sub-period read exists for volume_shock_1_50. Reading its sub-periods repeats the R-1 method on charged series and needs a dated declaration first (the specs' own sub_periods, both panels, none picked, non-gating, no look); proposed, not run. (2) turnover_per_session is 2 on every run row. With zero commission the cost is spread plus impact, and a mean session P&L of 3e-4 (reversal_21) or 6e-5 (volume_shock_1_50) per unit gross is within the range a one-way cost of a few basis points on 2 units of turnover would remove; whether 2 is the true traded turnover under the 5-session overlap or the kernel's gross rebalance convention is not established here, so turnover 2 is recorded as unverified and net expectation is unread, not negative. (3) Nothing here is promoted: positive net expectation and the single forward confirmation on the book's own unsearched span from 2025-12-24 (R-2) both still stand, and no book exists.

Owner question to add to 547: the S1 drift of cause 3 reaches family 10 (its members read S1 vintage_1 residuals and its spec declares `factor_spec: vintage_1`), so the 547 choice covers both families: certify the reversal members and book now, or hold the whole S1-dependent set (daily residual and family 10) until the rebuilt vintage and a fresh preregistration. The lead's working position is the hold; nothing is certified or promoted meanwhile.

Recommendation. Keep the hold for both S1-dependent families. Before any promotion step: (a) the owner rules on 547 with the family 10 reach; (b) declare and run the R-1 style sub-period read for volume_shock_1_50 on the recorded runs (next ledger line); (c) measure net expectation of reversal_21 with the first-cut cost model (unified design UD-12, costed kappa) as its own counted attempt once the S1 vintage question is settled; (d) freeze a book and spend the forward read once from 2025-12-24.

Numbers and their sources (for the second reader). Every figure is a read-only query; commands run from the repo root.
- Selection read (all adjusted p and StepM t, 16 attempts, 4,484 sessions, 2008-02-29 to 2025-12-23, reps 2,000, max horizon 5): `.venv/bin/python scripts/research/select_books.py --battery research/certificates/records/stepm_null_battery_s4000_2026-11-23.json --diagnostic` (exit 0, result true; ledger 2026-11-25b).
- Gross Sharpe, mean session P&L, turnover per session and run ids (737fe892, 1c4ff135, 07d6dfc3, 11f2076f): the `research_run` columns `gross_sharpe`, `mean_session_pnl`, `turnover_per_session` for completed vintage_1 rows, member name from `concept_registry` on `concept_id`.
- Raw p of volume_shock_1_50 core 0.209 and of the two volume_shock_5_50 runs 0.229 and 0.528: `decision_p` of runs 11f2076f, 38229ce1 and 881528b6.
- Charged rows 24 (16 completed, 8 failed) and budget_m 30: count of `research_run` rows of vintage_1 by status, and ledger 2026-11-25b.
- R-1 primary last sub-period mean 5.85e-5 and t 0.36: ledger 2026-11-23c.
- S1 dependence of family 10: `research/specs/family10_volume_shock_h5.yaml` (`factor_spec: vintage_1`) and `docs/plans/2026-11-15-family10-volume-shock-prereg-draft.md` section 3.
