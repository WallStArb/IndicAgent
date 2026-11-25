# Draft ledger entry: regime columns in the IC sweep

Status: draft for owner confirmation (lead ruling 2026-11-25, indicagent-46). Not in `docs/plans/methodology-change-ledger.md`; the lead writes the entry there only after the owner confirms it in the lead's own session.

## 2026-11-25c: the IC sweep recorder refuses regime-origin columns and the todo 674 members (todo 671; lead ruling, owner veto reserved)

The sweep recorder (`services/ic_sweep_recorder.py`, landed in 639c244b1) measures a per-session rank IC for every registered feature column at every horizon and records each cell as a counted attempt (E21). `ic_measure` has no admission gate for path-dependent columns, so the recorder applies the S0 member refusals itself: `refuse_path_dependent`, `refuse_builder_path_dependent` (todo 674, transitive), and regime origin. A refused column is left out of the sweep and listed in the report as `excluded_inadmissible`; it adds no attempt and no look.

Regime-origin columns differ from the other two. S0 admits a regime column when every covering batch comes from the walk-forward rebuild writer (`refuse_regime_columns`, B1j, todo 248). A sweep reads no batches, so it cannot make that check, and a regime column in a sweep series could carry a lookahead label with no way to tell. The recorder therefore leaves every regime column out.

Consequence: regime columns are not swept at level 1. They remain testable through S0 with the batch check, where the provenance is known. No threshold, spec, recorded statistic or counted look changes.

Question for the owner: confirm that regime columns stay out of the sweep. Recommendation: confirm. The alternative (read the covering batches in the recorder and admit walk-forward regime columns) adds a second reader of batch provenance and a path where a wrong provenance reads as clean; a regime family is better tested once, through S0, with its own spec and look count. Revisit only if a regime family is proposed that S0 cannot express.
