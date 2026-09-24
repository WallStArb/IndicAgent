# Phase 179 pre-registration: cross-asset sleeve walk-forward verdict

**Author:** Claude (Opus 5.5), 2026-09-24, at Brandon's request; parent plan
`docs/plans/2026-09-24-edge-proof-program.md`.
**Status:** DRAFT, not frozen. Freezes on the commit that adds the section 12 addendum (feature
exclusion list, code commit, snapshot hash), which must land before the walk-forward stage
produces any out-of-sample number. After that, any change is a `methodology-change-ledger.md`
entry.

## 1. The question

Does the production ensemble signal, refitted each year only on data available at the time,
carry allocation information across the 13-symbol cross-asset sleeve beyond what a
time-shifted copy of the same signal carries?

"Beyond a time-shifted copy" is the whole test. The shifted signal keeps the real signal's
distribution, persistence and cross-asset structure, including any static long or short tilt
(e.g. being structurally long GLD). Only its alignment with future returns is destroyed. A PASS
therefore means timing and allocation information, not a lucky persistent bet on an asset's
drift. The earlier diagnostic could not separate the two.

Verdict token: `SLEEVE_VERDICT = ACT | PASS | FAIL`, plus `FIDELITY = OK | BROKEN` (section 10).

## 2. Why the existing evidence does not answer it

Todo 378's diagnostic (ann. Sharpe ~1.19, `vol_normalized`) is not evidence for or against the
question above. Checked against the code on 2026-09-24:

- **Weight lookahead.** `alpha_events` for `run_2025122405150000` come from IC selection and
  weights fitted on all data through 2025-12-24; the diagnostic scored 2018-2026. About 92% of
  its window is in-sample for the signal.
- **Covariance lookahead.** `ensemble_trainer._process_stratum` fits the Ledoit-Wolf
  covariance (used for cluster deflation) on every `feature_vectors` bar in the stratum with no
  date bound, holdout included (todo 409).
- **Wall-clock weight aging.** The trainer ages quality weights by `now() -
  training_window_end`; past `alpha.ensemble.weight_stale_max_days` (90) it replaces them with
  uniform weights. The champion was trained 272 days after its window end, so the diagnostic's
  signal was a uniform blend of in-sample-selected features, not the method as designed
  (todo 408).
- **HMM parameter lookahead is a latent risk, not a present one.** Every 1d `feature_vectors`
  row carries `regime_label_source='filtered'` (full-sample-fitted `regime_writer` HMM
  parameters, the todo 248 defect). No `hmm_*` column is in the current 1d weights, but nothing
  in the method stops one from being selected at a refit. (`ctf_regime_align`, which is
  selected in 4 of the 7 production 1d strata, comes from a fixed-parameter forward filter,
  `feature_cache._hmm_forward_step` with module-constant parameters, so it is causal.)
- **Comparator.** `equal_weight` is long-only and signal-free.
- **Holdout already viewed.** The 2025-12-24 onward holdout was blended into the diagnostic's
  aggregate. It keeps value as a sign check (section 8), not as an untouched test set.

## 3. What is held fixed

| Item | Pinned value | Source |
|---|---|---|
| Sleeve | GLD, DBA, DBB, DBC, URA, TLT, UUP, VIXY, EMLC, HYG, XOM, DHI, PGR | Phase 174 cross-asset pre-registration; Gate A is correlation-only, Gate B did not bind (13/13 passed), so selection used no return information beyond Gate B's non-binding IC check |
| Timeframe | 1d | |
| Signal method | Production pooled cross-sectional IC, cluster-representative BH-FDR, IC shrinkage, meta-FDR eligibility, `select_features_per_stratum`, `resolve_stratum_weights` with `alpha.ensemble.weight_method` as of the snapshot, stratified by `market_regimes` `regime_group='equity'` labels | Reused code, section 4 |
| Pooling universe for IC | All symbols with 1d `feature_vectors` rows before the refit date | Production pools over the whole universe; a sleeve-only fit would test a different signal |
| Composite | `alpha = X @ (w * ic_sign)`, NULL feature = 0, no emission gate | `ensemble_trainer` step 6; `alpha_publisher` only filters on it |
| Execution | alpha from day D's close; enter at open D+1, exit at open D+2; return `ln(open[D+2]/open[D+1])` | Diagnostic `_EMBARGO_BARS = 2`, CLAUDE.md Invariant 1 |
| Portfolio arms (decision family) | `ic_proportional`, `vol_normalized`, `mean_variance`, gross exposure 1 | Diagnostic definitions, moved to a shared module unchanged |
| Instrument calibration | Diagnostic's trailing per-instrument IC, shrunk to the leave-one-out peer mean; point-in-time trailing coverage filter | Diagnostic, unchanged |
| Weight aging | `days_since = 0` at every refit (weights fitted at T are used from T) | Deviation D3 |

No arm is primary. `vol_normalized` was the best in-sample arm, so choosing it now would be
selection by looking; all three signal arms form the decision family under Holm (section 8).

## 4. Architecture

### 4.1 DAG

```
S0 snapshot (async I/O, read-only)
      │  content-hashed files: features, forward returns, regime labels, APR, registry
      ▼
S1 refit[k]  k = 2013..2025   (pure, one process per refit, parallel)
      │  per refit: IC cells → FDR → shrinkage → eligibility → stratum weights
      ▼
S2 score   (pure)  alpha for trading days in [T_k, T_k+1) with refit-k weights
      │  one date × symbol alpha panel, 2013-01 .. 2025-12-23
      ▼
S3 evaluate (pure)  3 arms on the real panel + every admissible shifted panel
      │
      ▼
S4 verdict  decision rules → result JSON + ledger row + concept_registry row
      ┆
S5 holdout read (once, after S4 is committed): refit at 2025-12-24, score the sealed holdout
```

Each node does one thing; data flows one way. S0 is the only node that touches Postgres, and it
opens its connection with `default_transaction_read_only = on`, so the harness cannot write
`feature_ic_scores`, `ensemble_weights` or anything else. S4 writes only its own outputs and
the governance records. Intermediate artifacts are files named by content hash, so any node can
be re-run and verified without re-running its parents.

### 4.2 Reuse map

The harness adds orchestration, not statistics. Every statistical step calls the code
production calls.

| Step | Reused code | Change needed |
|---|---|---|
| Pooled IC per cell | `services/ic_engine.py::_compute_one_cross_sectional_cell` (arrays in, rows out) | None. Imported, never copied. Importing a Ring 2 private function is recorded debt, resolved by todo 214, not here |
| Broadcast mask, cluster reps | Same function and its caller's representative selection | Extract the representative-selection loop from `_compute_cross_sectional_tf` into a pure helper both call |
| BH-FDR | `ic_math.apply_bh_fdr` | None |
| IC shrinkage | `scripts/ops/alpha/ops_ic_shrinkage.py::compute_shrinkage_updates` | Move to `src/intelligence/ensemble/shrinkage.py` if it isn't cleanly importable |
| Eligibility + meta-FDR + stratum fit | `ensemble_trainer._eligibility_where` semantics, `_meta_eligible`, `select_features_per_stratum`, `compute_shrinkage_covariance`, `resolve_stratum_weights` | Extract `_process_stratum`'s compute half into `src/intelligence/ensemble/stratum_fit.py::fit_stratum(ic_rows, X, config, days_since)`. The trainer calls it; `days_since` becomes an explicit argument (the trainer keeps passing its wall-clock value, so its behavior is unchanged) |
| Portfolio arms, calibration, instrument covariance | `scripts/analysis/portfolio_covariance_weighting_diagnostic.py` | Move to `src/intelligence/portfolio/weighting.py`; the diagnostic imports from there |
| Panel null | New `src/intelligence/statistics/panel_null.py`: deterministic enumeration of admissible circular date shifts of a whole panel, plus the permutation p-value | New. Deliberately not `alpha_score_residual`'s `sync_shift_null_p` (todo 372: per-symbol `k % m` breaks panel synchrony) |
| Manifest | `CorpusManifest` | None |

Both extractions (`fit_stratum`, representative selection) are behavior-preserving refactors,
each proved by an equivalence test on a fixture before the harness depends on it. After that,
the production statistics are identical by construction and section 10's live check only has to
cover data assembly.

### 4.3 Concurrency

- S0: one asyncpg pool; per-symbol fetches run concurrently. Column dtypes come from
  `conn.prepare(sql).get_attributes()`, never inferred from data (CLAUDE.md). The feature matrix
  is built straight from asyncpg rows into a float32 array; no wide DataFrame.
- S1: `ProcessPoolExecutor`, one refit per task. Workers are compute-only, memory-map the S0
  arrays read-only, and return rows. No worker opens a DB connection.
- S3: the shifted panels are independent. Chunks of shifts are spread across processes; within a
  chunk the arms are vectorized over dates.
- Everything is deterministic: the null is an exhaustive enumeration (no RNG), and every
  bootstrap inside reused code runs from a seed derived from the refit date and cell key.

### 4.4 Configuration

A frozen dataclass in `scripts/analysis/sleeve_walk_forward/config.py` holds this document's
constants (dates, purge, minimum shift, alpha levels). They are pre-registered test parameters,
not tunable system parameters, so they are APR-exempt and changing one is a methodology change.
Production parameters the reused code reads (IC, ensemble, FDR) come from one APR snapshot
taken in S0 and hashed into the manifest.

## 5. Data contract (S0)

- Rows: `feature_vectors` tf='1d', inner join `forward_returns` on (symbol, tf, bar_ts) with
  `return_type='executable_open_to_open'`, left join `market_regimes` on `regime_group='equity'`,
  tf='1d', ts=bar_ts; plus 1d OHLCV opens for the 13 sleeve symbols from
  `market_data_ohlcv_tradeable`.
- Bound: `bar_ts < alpha.validation.oos_start` (2025-12-24T05:15Z) for the main snapshot. The
  holdout rows are fetched only by S5, into a separate file. S0 asserts
  `max(bar_ts) < oos_start` and fails loudly otherwise.
- Candidate feature pool: every `FeatureVector` column, minus the exclusions pinned in the
  section 12 addendum, which are at least:
  1. Features computed from `regime_writer`'s fitted HMM outputs while stored labels are
     `regime_label_source='filtered'`: the `hmm_*` and `hmm_vol_*` columns and anything else a
     code audit of `feature_factory.py` finds reading them (the audit's output is the list).
     Fixed-parameter forward filters such as `ctf_regime_align` stay in.
  2. Features named in an open P0/P1 correctness todo at freeze time, and features built from
     them: currently todo 390's `amihud_illiq_z` and its product `illiquidity_momentum_product`.
     (Todo 390 is P2 today; it is promoted to P1 with this pre-registration because a divide by
     zero in a candidate feature can reach the weights.)
  3. `is_control` canaries (they are measured as controls, section 10, never weighted).
  4. `earnings_season_flag`, `days_since_quarter_end` and anything else production excludes by
     construction (`regime_scope='earnings_season'`).
- Present-day `concept_registry` status is not used to filter the pool. Status reflects
  decisions taken with later data, and the `feature_lifecycle` node landing with todo 402 will
  start flipping statuses on evidence. The two deprecated features (`new_high_flag`,
  `new_low_flag`) stay excluded if their transition reason is definitional or a data defect,
  and are included if it was performance-based. This is decided from the transition log alone,
  before any run.
- A feature enters refit k only if it has non-null values before T_k.

## 6. Walk-forward protocol (S1, S2)

- Refit dates T_k: first NYSE session of each year 2013 through 2025 (13 refits).
- Training rows for refit k: 1d bars from 2007 on, with bar_ts < T_k and the label fully
  realized before T_k. For scale h (`alpha.ic.lookahead.1d.*`: 1, 2, 5, 10), a row at bar t
  qualifies only if its exit open t+h+1 falls on or before the session five days before T_k
  (purge plus a 5-session embargo).
- Everything fitted at refit k uses only those rows: cell IC, walk-forward folds, bootstrap CIs,
  cluster structure, BH-FDR family, shrinkage priors, meta-FDR rates, the feature covariance for
  cluster deflation. `market_regimes` equity labels are causal by construction (causal expanding
  rank plus causal hysteresis), so they are read as stored.
- FDR family for refit k: all cluster-representative p-values from that refit's pooled 1d cells.
  This differs from production's corpus-wide family (all tfs, per-symbol plus pooled); see D1.
- Scoring (S2): for each trading day D in [T_k, T_{k+1}), alpha for each sleeve symbol comes
  from refit k's weights for D's equity-regime stratum. The final segment runs to the last
  session before `oos_start`. Days whose stratum has no weights get alpha = NaN, carried into
  S3 as "no position", counted and reported.
- Out-of-sample span: about 13 years, about 3,250 sessions.

## 7. Null and statistics (S3)

- Portfolio: for each arm and day, weights come from the diagnostic's machinery applied to the
  alpha panel up to D. Daily gross return `r_D = sum_i w_i,D * ret_i,D+1` (execution
  convention in section 3). Metric: annualized Sharpe of r over the out-of-sample span.
- Null: the whole date × symbol alpha panel is circularly shifted by k sessions, all symbols
  together, for every k with 63 <= k <= n-63. The portfolio stage reruns in full on each shifted
  panel, including instrument calibration and covariance, so the null sees exactly the pipeline
  the real signal sees. Panel-wide shifting keeps cross-asset signal correlation and
  persistence; the 63-session floor keeps slow features' autocorrelation from leaking alignment
  back in. There are about 3,120 admissible shifts, which puts the p-value resolution near 0.0003.
- Per-arm permutation p: `p = (1 + #{S_null >= S_obs}) / (1 + K)`. One-sided.
- Family: Holm across the three arms (valid under their dependence).
- Excess: `S_obs - median(S_null)` is the reported effect size.
- Stability: each arm's daily excess return over its null median, averaged within three pinned
  sub-periods (2013-2016, 2017-2020, 2021-2025).
- Reported CI: stationary bootstrap (mean block 21 sessions) of the excess Sharpe. Reported
  only; the permutation p decides.

## 8. Decision rules

Pinned before any out-of-sample number exists. N_tested = 15 (the ledger's 14 plus this test).

| Token | Condition |
|---|---|
| `FAIL` | Every arm's Holm-adjusted p >= 0.05, or the best-p arm's stability shows positive excess in fewer than 2 of 3 sub-periods |
| `PASS` | Some arm has Holm-adjusted p < 0.05, and that arm's excess is positive in >= 2 of 3 sub-periods |
| `ACT` | PASS, and that arm's Holm-adjusted p < 0.05 / 15, and after S5 its holdout excess return over the holdout null median is positive |

- The holdout (S5) is a sign check on the ACT arm. It cannot turn a FAIL into anything else; a
  negative holdout turns ACT into PASS.
- PASS opens a forward shadow run and phase 180's re-test with this method frozen. ACT also
  opens scoping of v4.0 phase 156. FAIL closes the sleeve in this form; phase 180 is then
  re-planned against the failure mechanism the diagnostics show, not run as scheduled.
- Costs never change the token (standing directive). They are reported per section 11.
- `FIDELITY = BROKEN` (section 10) means no token is issued at all.

## 9. Power

Out of sample is about 13 years. Using t ≈ excess IR × sqrt(years), one-sided:

| Level | Raw p the best arm needs (Holm, 3 arms) | t | Excess IR needed |
|---|---|---|---|
| PASS | < 0.0167 | 2.13 | ~0.59 |
| ACT | < 0.00111 | 3.06 | ~0.85 |

Daily serial dependence makes these optimistic. The synthetic power check (section 10, V3)
gives the harness's real power at excess IR 0.6. A true excess IR below about 0.4 will most
likely FAIL; that is the stated limit of what this test can see, and the record should call a
FAIL "no detectable timing information at this sample size", not "no signal".

## 10. Gates before any out-of-sample number

In order. A failure stops the phase and is written up; nothing is tuned to get past a gate.

| Gate | Check | Data it touches |
|---|---|---|
| V1 refactor equivalence | `fit_stratum` and representative-selection extractions: production outputs identical on fixtures; full unit suite green | Fixtures |
| V2 null calibration | Synthetic panel with no signal: PASS rate over 200 seeds within 5% ± 3.1% (binomial 95% band) | Synthetic |
| V3 power | Synthetic panel with planted excess IR 0.6: PASS rate reported; below 50% means the design is revisited before freezing | Synthetic |
| V4 fidelity | Refit at T = 2025-12-24 on the S0 snapshot. Fields of every harness pooled 1d row that don't depend on RNG draws (the addendum lists them from reading `_compute_one_cross_sectional_cell`; expected: ic_value, n, cluster_id, ic_sharpe_hac and anything derived only from them) match production `feature_ic_scores` for the same keys to 1e-6; RNG-dependent fields (bootstrap CIs and whatever depends on them) match within a Monte Carlo tolerance pinned in the addendum. Scoped to rows production computes the same way (its FDR family and status filter differ by design, D1/D4) | In-sample only |
| V5 controls | At every refit: `canary_acausal_placebo` is detected (passes the cell's own significance gate), proving the machinery can find leakage; the noise canaries pass FDR at no more than the nominal rate across refits; no canary ever receives a weight | In-sample per refit |
| V6 leakage asserts | Runtime asserts in S1: no training row's label exit on or after T_k minus embargo; no scored day before T_k; S0 max(bar_ts) < oos_start | All |

`FIDELITY = OK` requires V1, V4 and V5. V4 runs only on data before 2025-12-24, all of which is
in-sample for production already, so it spends nothing.

## 11. Diagnostics (reported, never decisive)

- Net-of-cost Sharpe per arm with a bps model per asset class (todo 393's fix), plus turnover.
- Per-year and per-sub-period excess; per-symbol contribution; per-equity-regime stratum.
- `equal_weight` long-only reference; a static-tilt reference (each symbol's time-averaged signed
  weight held constant), which isolates the tilt the null already absorbs.
- Uniform-weight variant (what production actually ran) and a production-pool variant with the
  D2 exclusions put back, to size deviations D2 and D3.
- Out-of-sample decay of each refit's selected features (IC in year k+1 vs its training IC).
- Days with no stratum weights, per year.

## 12. Freeze addendum (filled during the build, before S1 produces an out-of-sample number)

- Code commit hash of the harness and the reused modules.
- S0 snapshot hash and APR snapshot hash.
- Final excluded-feature list with one-line reasons (HMM audit output; open-todo features;
  controls; deprecated-feature decision).
- V2/V3 results and V4 tolerances.
- Compute measured for one refit, and the projected total.

## 13. Pinned deviations from production

| # | Deviation | Why | Sized by |
|---|---|---|---|
| D1 | FDR family = pooled 1d representatives per refit, not corpus-wide | The corpus-wide family can't be rebuilt per refit without a full recompute, and the ensemble consumes only pooled cells | V4 scope |
| D2 | Fitted-HMM features (`hmm_*`, `hmm_vol_*`) and todo 390's two columns excluded | Stored HMM labels carry full-sample parameters (todo 248); 390 is an unguarded division | Diagnostic variant |
| D3 | `days_since = 0` | Wall-clock aging is a defect (todo 408); weights fitted at T are fresh at T | Uniform-weight variant |
| D4 | No present-day status filter | Status is decided with later data | Section 5 |
| D5 | Covariance fitted on pre-T rows only | Production fits on all rows (todo 409) | None needed; strictly more causal |

## 14. Residual biases that remain

- **Survivorship in the pooling universe.** All 233 symbols are listed today (todo 376).
  Delisted names would have joined the pooled IC; their absence likely inflates the IC of
  distress-sensitive features. Direction: optimistic. Not fixable in this phase.
- **Design-time snooping.** Feature definitions and APR values were chosen by people who had
  seen the full history. The walk-forward can't remove that; it's why ACT also needs the holdout
  sign and why N_tested is counted.
- **Sleeve data depth.** TLT's 1d history starts in 2017 in this corpus (listed since 2002);
  the point-in-time coverage filter admits it when its trailing window fills, so it's absent from
  about the first four out-of-sample years.
- **Holdout viewed once in aggregate** (section 2); hence sign-check-only use.
- **Equity-regime strata for non-equity assets.** Production scores GLD or TLT with weights
  stratified by U.S. equity breadth/vol regimes. The harness reproduces this faithfully; an
  asset-class-aware variant is a separate future test that would count toward N_tested.

## 15. Build order

1. File todos 409 (trainer covariance over all bars) and 408 (wall-clock weight aging);
   promote todo 390 to P1.
2. `fit_stratum` extraction + representative-selection extraction + equivalence tests (V1).
3. Move the portfolio arms to `src/intelligence/portfolio/weighting.py`; diagnostic imports them;
   its tests stay green.
4. `panel_null.py` with tests.
5. Harness S0-S4 with synthetic end-to-end tests; run V2, V3.
6. HMM-feature audit, deprecated-feature decision, S0 snapshot, V4, V5 at T = 2025-12-24.
7. Commit the section 12 addendum. The pre-registration is frozen here.
8. S1-S4 once. Commit the result JSON and the ledger row.
9. S5 holdout read. Commit the final token.
10. `/simplify`, `/code-review`, independent review of the verdict doc (AGY; Codex when its quota
    resets).

Steps 2-4 are ordinary engineering on shared code and follow the Done-Coding SOP. Nothing in
steps 1-7 computes an out-of-sample number.
