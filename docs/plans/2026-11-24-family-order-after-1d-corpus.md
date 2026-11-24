# Family order once the 1d feature corpus exists

Status: design note for the lead (indicagent-ee), 2026-11-24, drafted by an Opus research pass and spot-checked (cited paths and code symbols verified to exist; ledger and todo claims are the drafter's). Not a preregistration; no look is charged and no number is computed. Facts were read from the repo at origin/main on 2026-11-24, plus light read-only SELECTs.

## Look accounting, verified

`research_run` on 2026-11-24 holds 20 vintage_1 rows, all `kind = evidence`, `mode = real`: 12 `completed` with one series each, and 8 `failed` with no snapshot and no series (three daily residual, ledger 2026-11-22b; one family 9, 2026-11-23h; four family 10, 2026-11-24b). There are no `book_test` rows. Only `refused` and `guard_failed` go uncharged (`UNCHARGED_STATUSES`, `src/intelligence/research/ledger.py:46`), so 20 rows are charged. The family 10 relaunch adds 4 rows and 4 series, for 24 charged rows and 16 StepM series, which matches the lead's figure.

"6 remaining" overstates how binding the 30 is. Under E18 the evidence count has no cap: `alpha.research.budget_m` (30) only divides the book test's power bar (`screen_alpha / M` = 0.00167, `runner.py:2072`) and is disclosed on `book_test` rows (`ledger.py` `start_runs` docstring; `config_schema`). A look really costs a tighter StepM correction on every attempt: each completed member-panel adds one series, and a failed row with no series adds none (2026-11-22g). A conservative Bonferroni bound on the one-sided z needed is 2.73 at 16 series, 2.94 at 30, 3.29 at 100 and 3.89 at 1,000; StepM's joint draw prices correlated series below that (design section 7.3). `reversal_21` was selected at t 3.46 and 3.84 on 10 series (2026-11-23a), and that read has not been redone on 12 or 16.

Recommendation: keep M at 30. Raising it lowers the power bar, so more books get refused for being underpowered, and the key's own description says any change needs a methodology-change-ledger entry, not an APR write. If the lead wants a planning budget, declare one in a ledger line, counted in series rather than rows: 14 series remain under 30 after family 10.

## What the corpus adds, and what it cannot test

The corpus adds stored 1d columns (310 in `feature_vectors`, 280 applicable at 1d and 277 judgeable at N = 1,000; ledger 2026-11-22d). It also adds the 13 numeric HMM columns (7 trend, 6 volatility) and the `regime` labels. That opens up feature, factor and regime families, which the price-only panels could not express. Limits:

- E21 lift. The 2026-11-22 lift covers price-derived 1d families only. Every feature-vector family needs its own clean-data ruling.
- Scope. The corpus is 1d only (STATE lane C; `ic_tfs` 1d, todo 471). No intraday member is in scope.
- `no_fill`. Warmup is masked by declared memory (B1g). Path-dependent columns are refused. A regime column is refused unless every covering batch comes from the rebuild writer (B1j, `feature_inputs.refuse_regime_columns`).
- The runner cannot run a corpus family as registered. Input members run only at horizon 1, equal weight, in one family, never beside residual-return members (`runner._check_supported_subset`, `_check_input_mix`; todo 588 m3). The passing certificates are feature 1h to 1d, feature 15m to 1d and `rk_high_dist` 126 1d to 1d, all at horizon 1 (`null_battery_persistent._REPORT_PASSING`). No stored 1d to 1d feature route is certified, and every family since E23 is h = 5. Every corpus family therefore waits on one shared build: a horizon-5 1d feature route in the runner and new persistent battery cells at the largest memory any member declares, which is a counted battery run under E17 with seed bases declared first. `_check_supported_subset` is outside `RUNNER_STATISTIC_FUNCTIONS` (`battery_pass.py:59`), so widening it does not stale the bound passes. An edit to `families/common.py` does.
- Kernels. A family cannot dodge the corpus by recomputing a stored column as a kernel at its stored window (design D5, `kernel_source.py` docstring).
- Quality. Fundamentals are not stored (ledger section 3), so quality is not testable.

## Ranked candidates

Series = members x horizons x panels (E18, E23 section 4); all at h = 5 on the primary and core panels. "Shared build" means the h5 1d input route and its battery cells described above.

| Rank | Family (source) | Hypothesis | Columns | Series | Battery | Prior | Overlap with counted series | Coupling | Early kill, no look |
|---|---|---|---|---|---|---|---|---|---|
| 1 | H-B low risk (E23, `docs/plans/2026-11-15-published-prior-top3-prereg-drafts.md`) | High MAX, idiosyncratic vol and beta earn less, sign -1 | `max_daily_return` (21), `idiosyncratic_volatility` (21), `equity_beta_z` (60, z 252) | 6, already declared | shared build | weak to moderate: slow and published, but 96 percent of the frictions category fails (Hou, Xue and Zhang, cited there) | MAX and `reversal_21` both use 21-session windows | `features.py`, `null_battery_persistent.py` | todo 564 constant or all-null check; finite share per year; signal-to-signal rank correlation with `reversal_21` (reads no target); synthetic h5 power |
| 2 | `corpus_family`, equal weight, in-fold signs (design section 6, attempt 5) | The admitted columns together carry timing the price-only families lack | every column that passes the guards | 2 (one book per panel) | shared build plus a multi-input book certificate (only one composition is certified, `CERTIFIED_BOOKS`) | unclear: effective breadth about 8.4 of 230 (ledger section 5); phase 179 failed in the wrong vehicle | partly, via family 9's price-position columns (null) | runner book path, battery book cells | battery size at the real member count; S3 probes; coverage floor |
| 3 | Market-residual reversion (ledger section 3, stat arb row; `kernels/residual.py`) | A large residual move against SPY reverses | `market_residual_z` (252), optionally `market_residual_lag1_acf` (63) | 2 to 4 | shared build | moderate, but `informed_by` the selected `reversal_21` | high: the same mechanism at a 1-day signal | as rank 1 | turnover estimate against the todo 553 spreads; signal correlation with `reversal_21` |
| 4 | Regime-conditioned `reversal_21` (ledger section 3; design 5.2 rule 3; todo 548) | `reversal_21` pays more in turbulent volatility states | `hmm_vol_prob_turbulent`, or the equity `market_regimes` vol z | 2 per variant | new: S7 regime slot cells | poor: 0 of 270 persistence cells, 0 of 249 earnings cells | `informed_by` `reversal_21` and its R-1 decay | needs a base book; `book_memory` reach (todo 548) | episode count; synthetic power at the observed episodes |
| 5 | `interaction_family` (`docs/research/intel-feature-interaction-factory.md`) | 20 to 30 theory-motivated pairwise terms | stored `*_product` columns plus new terms | 2 as one book; 40 to 60 as members | shared build plus book cells | weak: pilot 22.2 percent at BH-FDR, never at scale | unclear | new kernels | run as one book only, never per term |
| 6 | `size_proxy` (584 add-list) | Small names earn more | `size_proxy` (63) | 2 | shared build | weak after 1980; dividend-linked (todo 666) | low | as rank 1 | todo 666 materiality first |
| 7 | Cross-sectional momentum from stored columns (ranked backlog) | Raw momentum ranks predict | `momentum_z_slow`, `momentum_z_mid` | 4 | shared build | weak: residual momentum was null (t 0.99 and 1.44, 2026-11-22c) | high with M1 and M2 | as rank 1 | likely redundant (`docs/ideas/ranked-backlog-2026-11-15.md`); park |

Out of the table: the todo 281 statistics (no stored column) and AL's s-score (research layer by decision, `kernels/residual.py`).

## Recommended order and stopping rule

1. Re-read StepM on 16 series after family 10. Then put the `reversal_21` book decision (todo 547, owner) before any corpus series. The corpus families should not dilute the one detection while the book is still unfrozen. Adding attempts after the freeze is allowed, and E18's forward confirmation covers the adaptive gap.
2. Do the shared build and its battery block. Its cost falls on every corpus family, so build it once.
3. H-B, 6 series, already registered: the cheapest corpus test.
4. `corpus_family`, 2 series. It answers "do features add" for the fewest series.
5. Market-residual reversion, only if its turnover clears the cost check.
6. The regime variant, only after a base book exists.
7. Ranks 5 to 7 wait.

That spends 8 series and reaches 24 of the 30 planning budget.

Stopping rule:
- Stop spending vintage_1 series on prior families when either (a) a book holding a selected member is frozen, after which effort goes to its forward power plan, or (b) the universe reaches 30 series with no new selected member, after which the next look is one `generated_family` attempt (todo 440) or new data. A vintage extension does not reset the count (E18 point 3).
- A family whose no-look check fails is not run, and no row is opened. That includes battery size, coverage, or synthetic power below 0.5 at its published effect under the current StepM bar.

Fewer, stronger hypotheses protect the one marginal detection and the heavy slot; the cost is that rank 2, the most value per series, carries the most build.

## Regime columns

The 13 HMM columns are object dependent: a value exists only where a segment is written (2026-11-24d). Rules for a regime-segmented spec:
- A name-day without a written segment is NaN, never a state and never a default bucket.
- The spec discloses the per-year share of member cells that have a written segment (`pilot_hmm_written_share`).
- Degenerate-occupation refusal is a causal but non-random selection on each name's own path (todo 583: at K = 3, 21.5 percent of 1d segments refused and 1.7 percent of names with no output). That selection must be stated, not corrected.
- A contrast that recomputes the unconditional member on the same name-days is a new series and is counted.
- Conditioning enters only as one pre-registered S7 variant on continuous states, never on buckets (design 5.2).

Before the rebuild, the columns carried the todo 451 mask and the full-history fit (todo 248). B1j refuses those batches. The 303 and 304 verdicts are biased toward dead and are not evidence against a regime family (todo 466). `market_regimes` ends 2026-08-11 in every group, so it is fine for vintage_1 but stale for shadow.

## IC measure versus runner

`ic_measure` is a measurement and proposer (`alpha.ic_measure.horizons` 1d: 1, 2, 5, 10). Counted looks go through the runner. E21 counts every measured cell as a `research_run` evidence attempt. However, `services/ic_measure.py` writes only `feature_ic_scores`, and no writer of cell series exists outside the runner ledger (grep: `research_run_series` appears only in `ledger.py`, `select_books.py`, `backfill_attempt_series.py` and `replication_subperiods.py`). E21 says no real-data sweep runs until that writer is built.

A full level 1 sweep would add about 277 x 4 = 1,100 cells to the 16 series. So:
- The prior-driven families run first, since they need no IC proposal.
- The sweep comes after, with `n_looks` declared and a synthetic StepM check of the selected series against that many correlated null cells.
- Any family the sweep prompts carries `informed_by`.

Todo 666 is decided before the first sweep. Its prescribed comparison (IC with and without a total-return target) is itself an IC look, so decide on return-free facts: the share of target rows that straddle an ex-date in coverage, and the yield distribution. Alternatively, count the comparison.

## Risks and questions for the owner

1. Clean-data ruling for the feature families (outside the 2026-11-22 lift).
2. Whether the `reversal_21` book is frozen before the corpus series (todo 547). R-1 shows a late-period t of 0.36 on primary (2026-11-23c).
3. Forward power. Books with `feature_vectors` members confirm only after their freeze and never before 2026-08-08, and a power-dated test more than 3 years out refuses promotion (E18). Slow, low-IC members such as H-B may never confirm; check this synthetically before running.
4. Total-return thinning. For the member universe, dividend coverage is 59.7 percent of member cells (6,162 of 11,684 member names), and all 5,292 uncovered member names are dead (ledger 2026-11-21d, corrected by 2026-11-24j). The 0.819 uncovered share (core 0.496) is the family 9 primary panel's, not the universe's (ledger 2026-11-23i). Every total-return family is scored mostly on covered live names, which is a survivorship tilt to disclose or fix.
5. The shared battery block and the corpus rerun compete for the one heavy slot under the DIMM cap (2026-11-24b).
6. Unclear: whether the joint draw keeps 1,100 correlated sweep cells cheap enough to leave `reversal_21` selected.
