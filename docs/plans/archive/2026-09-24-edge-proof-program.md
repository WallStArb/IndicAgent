# Edge proof program (v3.4) - archive stub

Program plan, 2026-09-24 (AGY-reviewed). Superseded 2026-09-26 by the unified research-to-production design and 2026-10-31 at the program level by `docs/plans/2026-10-31-data-fill-and-corpus-rerun-plan.md`. Milestone v3.4 closed 2026-09-26: 179 and 181 verdicts FAIL, 178 and 182 complete, 177 and 180 superseded. Rationale and outcomes: `.planning/ROADMAP.md` "v3.4 rationale" and `.planning/MILESTONES.md`.

Ideas worth keeping:

- Rank levers by power, not readiness: a weight-level walk-forward was placed first because it was the only lever that could turn 9 months of true OOS into about 7 years of pseudo-OOS and produce a verdict within weeks; throughput work was deliberately kept off that critical path.
- The decision comparator must be the same arm fed a null signal (circular shift), not a long-only equal-weight reference; beating a signal-free arm proves nothing about the signal.
- Power accounting against excess-over-null, not standalone Sharpe: the 2026-09-24 cross-asset diagnostic (Sharpe about 1.19) was mostly in-sample (about 90% of the window scored weights fitted through 2025-12-24), wrongly compared, and underpowered (t about 1.0 on the 9-month holdout). Never cite it as edge evidence.
- Effective breadth, not column count: about 8 independent bets out of 290 feature columns; each construction test spends multiplicity budget (meta-FDR, alpha/N_tested).

Verdict record: `docs/research/construction-verdict-ledger.md`, `.planning/MILESTONES.md` (v3.4).

Full text in git history: `docs/plans/2026-09-24-edge-proof-program.md` as of commit `8b4f2c9c4` (pre-condense) and `a784af281` (condensed status page).
