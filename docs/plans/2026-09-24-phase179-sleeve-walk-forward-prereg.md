# Phase 179 pre-registration: cross-asset sleeve walk-forward verdict

**Author:** Claude (Opus 5.5), 2026-09-24, at Brandon's request; parent plan
`docs/plans/2026-09-24-edge-proof-program.md`.
**Status:** DRAFT, revised after AGY adversarial review (section 16), not frozen. Freezes on the commit that adds the section 12 addendum (feature
exclusion list, code commit, snapshot hash), which must land before the walk-forward stage
produces any out-of-sample number. After that, any change is a `methodology-change-ledger.md`
entry.

## 1. The question

Does the production ensemble signal, refitted each year only on data available at the time,
carry allocation information across the 13-symbol cross-asset sleeve beyond what a
time-shifted copy of the same signal carries?

"Beyond a time-shifted copy" is the whole test. The shifted signal keeps the real signal's
distribution, persistence and cross-asset structure; only its alignment with future returns is
destroyed, and the whole portfolio pipeline (calibration included) is rerun on it. A signal
that only tracks an asset's drift gets no credit: under the null the pipeline's calibrated IC is
noise for the real run and the shifted runs alike, so drift earns nothing systematic in either.
A PASS therefore means timing and allocation information. The earlier diagnostic could not
separate the two.

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
| Pooling universe for IC | The `equity` regime group's symbols, resolved by production routing (`ic_engine._build_symbol_regime_class`, 222 symbols at the snapshot), with 1d rows before the refit date | The trainer joins strata only to `regime_group='equity'` labels, so only equity-group pooled cells ever produce weights; commodity, rates and fx pooled cells are measured but never weighted. The sleeve is scored with equity-learned weights (section 14) |
| Composite | `alpha = X @ (w * ic_sign)`, NULL feature = 0, no emission gate | `ensemble_trainer` step 6; `alpha_publisher` only filters on it |
| Execution | alpha from day D's close; enter at open D+1, exit at open D+2; return `ln(open[D+2]/open[D+1])` | Diagnostic `_EMBARGO_BARS = 2`, CLAUDE.md Invariant 1 |
| Portfolio arms (decision family) | `ic_proportional`, `vol_normalized`, `mean_variance`, gross exposure 1 | Diagnostic definitions, moved to a shared module unchanged, including its 504-session warmup (`_INITIAL_WARMUP_BARS`) |
| Instrument calibration | Diagnostic's trailing per-instrument rank IC over the same 504-session window, shrunk to the leave-one-out peer mean; an instrument whose paired (alpha, forward return) rows cover < 95% of the window gets IC 0 (no position) | Diagnostic method with its coverage bar matched to the covariance's (the diagnostic itself keeps its 20-pair floor, per its spec) |
| Instrument covariance | Ledoit-Wolf on realized log returns over the trailing 504 sessions, date axis = NYSE sessions; admitted with a return on the window's last row and on >= 95% of the window, jointly (lowest-coverage instrument dropped, ties by name, until complete rows clear 95%); fitted on complete rows, never zero-filled | `src/intelligence/portfolio/weighting.py::instrument_covariance`, revised 2026-09-24 (build step 3) |
| Weight aging | None: the fit has no clock (production too since todo 408) | D3 |

No arm is primary. `vol_normalized` was the best in-sample arm, so choosing it now would be
selection by looking; all three signal arms form one decision family under the max-statistic
permutation adjustment (section 7).

## 4. Architecture

### 4.1 DAG

```
S0 snapshot (async I/O, read-only)
      │  content-hashed files: features, forward returns, regime labels, APR, registry
      ▼
S1 refit[k]  k = 2011..2025   (pure, one process per refit, parallel)
      │  per refit: IC cells → FDR → shrinkage → eligibility → stratum weights
      ▼
S2 score   (pure)  alpha for trading days in [T_k, T_k+1) with refit-k weights
      │  one date × symbol alpha panel, 2011-01 .. 2025-12-23
      ▼
S3 evaluate (pure)  3 arms on the real panel + every admissible shifted panel;
      │  trading span 2013-01 .. 2025-12-23 (2011-2012 is the portfolio warmup)
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
| Pooled IC per cell | `services/ic_engine.py::_compute_one_cross_sectional_cell` and `_compute_one_broadcast_cell` (arrays in, rows out) | Run for every enabled regime group (equity, rates, commodity, fx; amendment A1) so the BH family and the meta-FDR denominator match production's pooled 1d set; only equity strata are weighted. Imported, never copied. The cell function expects all `_FEATURE_NAMES` columns, so the harness always passes the full matrix and removes excluded features through the `broadcast_mask` argument (masked columns leave X_nd and emit no rows), extended with the section 5 exclusions. Importing Ring 2 private functions is recorded debt, resolved by todo 214, not here |
| Symbol routing | `ic_engine._build_symbol_regime_class` | None |
| Cluster representatives | `ic_engine._mark_cluster_representatives`, called by both passes | Done 2026-09-24 (7fa346137, todo 410) |
| BH-FDR | `ic_math.apply_bh_fdr` | None |
| IC shrinkage | `scripts/ops/alpha/ops_ic_shrinkage.py::compute_shrinkage_updates` | Prior bucket built from the refit's pooled rows only (D7) |
| Eligibility + meta-FDR + stratum fit | `ensemble_trainer._eligibility_where` semantics, `_meta_eligible`, `src/intelligence/ensemble/stratum_fit.py::select_stratum` and `fit_stratum_weights(selection, X, bar_ts, ...)` | Done 2026-09-24 (c6750d700): the trainer calls the same two functions. No aging (todo 408 deleted it; migration 360); the covariance window cut (bars <= the IC window end, todo 409) lives inside `fit_stratum_weights`, so the harness gets it by construction |
| Portfolio arms, calibration, instrument covariance | `src/intelligence/portfolio/weighting.py` | Done 2026-09-24 (build step 3). Moved from the diagnostic, which imports it; thresholds are arguments. The walk-forward orchestration (`run_walk_forward`, with todo 393's wrong cost proxy) stays in the diagnostic: the harness builds its own array-first engine on these primitives in step 5 |
| Panel null | New `src/intelligence/statistics/panel_null.py`: deterministic enumeration of admissible circular date shifts of a whole panel, plus the permutation p-value | Done 2026-09-24 (edb555a11). Deliberately not `alpha_score_residual`'s `sync_shift_null_p` (todo 372: per-symbol `k % m` breaks panel synchrony) |
| Manifest | `CorpusManifest` | None |

Both landed with tests: the stratum fit's equivalence against `resolve_stratum_weights`
plus regression tests for 408 and 409, and the representative helper's test that puts the
max-|IC| candidate second. After that, the production statistics are
identical by construction except for that fix, and section 10's live check covers data assembly
and the fields the fix doesn't touch.

### 4.3 Concurrency

- S0: one asyncpg pool; per-symbol fetches run concurrently. Column dtypes come from
  `conn.prepare(sql).get_attributes()`, never inferred from data (CLAUDE.md). The feature matrix
  is built straight from asyncpg rows into a float32 array; no wide DataFrame.
- S1: `ProcessPoolExecutor`, one refit per task. Workers are compute-only, memory-map the S0
  arrays read-only, and return rows. No worker opens a DB connection.
- S3: the return covariance at each date depends only on returns, so it is computed once and
  shared by the real run and every shift. The per-instrument IC calibration depends on the
  alpha panel, so it is recomputed per shift in a numba kernel (trailing rank correlation), with
  chunks of shifts spread across processes. The measured cost of one shift goes in the
  addendum; if the projected total exceeds 24 hours, the design is revisited before freezing,
  never by thinning the null silently.
- Everything is deterministic: the null is an exhaustive enumeration (no RNG), and every
  bootstrap inside reused code runs from a seed derived from the refit date and cell key.

### 4.4 Configuration

A frozen dataclass in `scripts/analysis/sleeve_walk_forward/config.py` holds this document's
constants (dates, purge, minimum shift, alpha levels). They are pre-registered test parameters,
not tunable system parameters, so they are APR-exempt and changing one is a methodology change.
Production parameters the reused code reads (IC, ensemble, FDR) come from one APR snapshot
taken in S0 and hashed into the manifest.

## 5. Data contract (S0)

- Rows: `feature_vectors` tf='1d' for the equity group's symbols (IC and weights) and the 13
  sleeve symbols (scoring), inner join `forward_returns` on (symbol, tf, bar_ts) with
  `return_type='executable_open_to_open'`, left join `market_regimes` on `regime_group='equity'`,
  tf='1d', ts=bar_ts; plus 1d OHLCV opens for the 13 sleeve symbols from
  `market_data_ohlcv_tradeable`, and their 1d closes (the instrument covariance uses realized
  close-to-close returns; amendment A4).
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

- Refit dates T_k: first NYSE session of each year 2011 through 2025 (15 refits). The 2011 and
  2012 refits exist to fill the portfolio's 504-session warmup; they produce alpha, not trades.
- Training rows for refit k: 1d bars from 2007 on, with bar_ts < T_k and the label fully
  realized before T_k. For scale h (`alpha.ic.lookahead.1d.*`: 1, 2, 5, 10), a row at bar t
  qualifies only if its exit open t+h+1 falls on or before the session five days before T_k
  (purge plus a 5-session embargo). Implemented the way the cell function already expects:
  X_raw is trimmed at the h=1 cutoff, and `complete_mat[t, scale]` is set False for every longer
  scale whose exit falls past its own cutoff.
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
- Out-of-sample trading span: 2013 through 2025-12-23, about 13 years, about 3,250 sessions.

## 7. Null and statistics (S3)

- Portfolio: for each arm and day, weights come from the diagnostic's machinery applied to the
  alpha panel up to D. Daily gross return `r_D = sum_i w_i,D * ret_i,D+1` (execution
  convention in section 3). Metric: annualized Sharpe of r over the out-of-sample span.
  Sharpe, not Sortino or a deflated Sharpe, decided 2026-09-24 before any run: the p-value
  comes from ranking against the shifted panels, which carry the same fat tails, skew and
  autocorrelation, so any statistic is valid and the choice is about power and meaning.
  Sortino's downside-only denominator is estimated from about half the days, which widens the
  null and costs power this sample can't spare, and it rewards return shape rather than the
  timing and allocation skill under test. Deflated and HAC-adjusted Sharpe correct for
  multiplicity and autocorrelation, which the Westfall-Young adjustment and the null already
  handle. One pre-committed statistic; the shape measures are section 11 diagnostics.
- Null: the whole date × symbol alpha panel is circularly shifted by k sessions, all symbols
  together, for every k with 63 <= k <= n-63. The portfolio stage reruns in full on each shifted
  panel, including instrument calibration and covariance, so the null sees exactly the pipeline
  the real signal sees. Panel-wide shifting keeps cross-asset signal correlation and
  persistence; the 63-session floor keeps slow features' autocorrelation from leaking alignment
  back in. The shifted panel is the whole S2 alpha panel (2011-01 through 2025-12-23, about 3,750 sessions), since the warmup years feed calibration and standardization; about 3,620 admissible shifts, p-value resolution near 0.0003 (amendment A3).
- Multiplicity: Westfall-Young max-statistic permutation adjustment across the three arms,
  which uses the exact joint null the shared shifts already produce. For each arm j,
  standardize by its own null: `Z_j = (S_j - mean(S_j_null)) / sd(S_j_null)`, and likewise for
  every shift. With `M_k = max_j Z_j(k)`, the adjusted one-sided p for arm j is
  `(1 + #{k: M_k >= Z_j_obs}) / (1 + K)`. This controls the family-wise error strongly and,
  unlike Holm, doesn't pay for the three arms being highly correlated.
- Excess: `S_obs - median(S_null)` is the reported effect size.
- Stability: each arm's daily excess return over its null median, averaged within three pinned
  sub-periods (2013-2016, 2017-2020, 2021-2025).
- Reported CI: stationary bootstrap (mean block 21 sessions) of the excess Sharpe. Reported
  only; the permutation p decides.

## 8. Decision rules

Pinned before any out-of-sample number exists. N_tested = 15 (the ledger's 14 plus this test).

An arm qualifies if and only if its adjusted p < 0.05 and its excess is positive in at least 2
of the 3 sub-periods.

| Token | Condition |
|---|---|
| `FAIL` | No arm qualifies |
| `PASS` | At least one arm qualifies |
| `ACT` | PASS, and some qualifying arm has adjusted p < 0.05 / 15, and after S5 that arm's holdout excess return over its holdout null median is positive. If several qualify at that level, the one with the smallest adjusted p is the ACT arm |

- The holdout (S5) is a sign check on the ACT arm. It cannot turn a FAIL into anything else; a
  negative holdout turns ACT into PASS.
- PASS opens a forward shadow run and phase 180's re-test with this method frozen. ACT also
  opens scoping of v4.0 phase 156. FAIL closes the sleeve in this form; phase 180 is then
  re-planned against the failure mechanism the diagnostics show, not run as scheduled.
- Costs never change the token (standing directive). They are reported per section 11.
- `FIDELITY = BROKEN` (section 10) means no token is issued at all.

## 9. Power

Trading span about 13 years. Using t ≈ excess IR × sqrt(years), one-sided, and treating the
max-statistic adjustment as no looser than Holm for the best arm (conservative; it is less
strict when the arms are correlated, as they are):

| Level | Critical t (best arm) | Excess IR at 50% power | Excess IR at 80% power |
|---|---|---|---|
| PASS | 2.13 | ~0.59 | ~0.82 |
| ACT | 3.06 | ~0.85 | ~1.08 |

A true excess IR of 0.59 is a coin flip to PASS, not a likely one. Daily serial dependence
makes all of these optimistic; the synthetic check (section 10, V3) measures the harness's
real power at excess IR 0.6 and 0.8. A FAIL is recorded as "no detectable timing information at
this sample size", not "no signal".

## 10. Gates before any out-of-sample number

In order. A failure stops the phase and is written up; nothing is tuned to get past a gate.

| Gate | Check | Data it touches |
|---|---|---|
| V1 refactor equivalence | `fit_stratum` and representative-selection extractions: production outputs identical on fixtures; full unit suite green | Fixtures |
| V2 null calibration | Synthetic panel with no signal: PASS rate over 200 seeds within 5% ± 3.1% (binomial 95% band). Each seed uses a random subsample of 199 admissible shifts (a valid Monte Carlo permutation test); the real run uses all of them | Synthetic |
| V3 power | Synthetic panels with planted excess IR 0.6 and 0.8: PASS rates reported; below 50% at 0.8 means the design is revisited before freezing | Synthetic |
| V4 fidelity | Refit at T = 2025-12-24 on the S0 snapshot, with production's own feature mask (no section 5 exclusions) and the equity-group universe, both cell paths (cross-sectional and broadcast). Fields of every harness pooled 1d row that don't depend on RNG draws (the addendum lists them from reading `_compute_one_cross_sectional_cell`; expected: ic_value, n, cluster_id, ic_sharpe_hac and anything derived only from them) match production `feature_ic_scores` for the same keys to 1e-6; RNG-dependent fields (bootstrap CIs and whatever depends on them) match within a Monte Carlo tolerance pinned in the addendum. `bh_adjusted_p` and `passes_fdr` are excluded from V4: the FDR family differs by design (D1) and production's flags carry todo 410 (D6) | In-sample only |
| V4b shrinkage-prior sizing (D7) | At T = 2025-12-24 on production's stored rows, run selection and the stratum fit with production's `ic_shrunk` and with the pooled-only prior. Any equity stratum whose selected feature set differs adds a per-symbol 1d pass to S1 before freezing | In-sample only |
| V5 controls | At every refit: `canary_acausal_placebo` is detected (passes the cell's own significance gate), proving the machinery can find leakage; the noise canaries pass FDR at no more than the nominal rate across refits; no canary ever receives a weight | In-sample per refit |
| V6 leakage asserts | Runtime asserts in S1: no training row's label exit on or after T_k minus embargo; no scored day before T_k; S0 max(bar_ts) < oos_start | All |

`FIDELITY = OK` requires V1, V4 and V5. V4 runs only on data before 2025-12-24, all of which is
in-sample for production already, so it spends nothing.

## 11. Diagnostics (reported, never decisive)

- Net-of-cost Sharpe per arm with a bps model per asset class (todo 393's fix), plus turnover.
- Per arm: Sortino, max drawdown, skew, excess kurtosis and daily hit rate, for the real run and
  the null median. They inform sizing if the token is PASS or ACT; they never change it.
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

### 12.1 Entries recorded so far (2026-09-24)

- **V2 null calibration: PASS.** 200 no-signal synthetic seeds (persistent AR(1) alpha,
  phi = 0.98, per-asset drift, equicorrelated returns), 199 admissible shifts each: PASS rate
  6.0% (12/200), inside the pinned 5% +/- 3.1% band; mean vol_normalized excess Sharpe 0.0003.
  Harness at main 549014a6b. Artifact `logs/phase179/v2_73b7519777738654.json`.
- **HMM-feature audit.** `regime_writer` owns 16 `feature_vectors` columns; 3 are
  `FeatureVector` fields (`hmm_regime_prob`, `hmm_entropy`, `hmm_duration`) and are excluded;
  `feature_factory` writes them as None and no other writer derives a feature from any of the
  16. `momentum_vol_regime_product` is `momentum_z_fast x hv_ratio` (no HMM input) and stays;
  `ctf_regime_align` and FeatureCache's inline K=3 filter use fixed parameters and stay.
- **Exclusion list** (`scripts/analysis/sleeve_walk_forward/excluded_features.json`), two tiers:
  exclude (never measured): the 3 fitted-HMM columns, todo 390's `amihud_illiq_z` and
  `illiquidity_momentum_product`, `earnings_season_flag`, `days_since_quarter_end`; control
  (measured every refit for V5, never selected or weighted): the 5 `canary_*` features. The
  todo-390 entries are re-checked against open P0/P1 correctness todos at freeze.
- **V4b (D7 sizing): PASS, and D7 is null in practice.** At the production window
  (2025-12-24 05:15 UTC, 1,508,020 1d rows) the selected feature set is identical in all 9
  equity strata under both priors, with quality-weight rank correlation 1.000 and bit-identical
  `ic_shrunk`. Cause: the 1,146,900 per-symbol 1d rows are all `reliable` but none has an
  `ic_sharpe_hac` (a per-symbol 1d cell is too short for 2,000-row Sharpe windows with a 30-window
  minimum), and `compute_shrinkage_updates` only takes rows with one, so production's 1d bucket
  is pooled-only too. Correction to D7's own rationale: its "143,100 per-symbol vs 1,160 pooled"
  counted reliable rows without the `ic_sharpe_hac` filter, so it overstated the deviation. No
  per-symbol pass is needed. Artifact `logs/phase179/v4b_20260924T193132Z.json`. Also observed:
  `high_bull` and `low_bull` select no features under either prior (few eligible pooled cells);
  their days get no alpha, which S2 counts per year.
- **Deprecated-feature decision: moot.** `new_high_flag` and `new_low_flag` were deprecated by
  operator override with no gate metric and are no longer `FeatureVector` fields (migration 284
  tombstones), so they cannot enter the pool.

## 13. Pinned deviations from production

| # | Deviation | Why | Sized by |
|---|---|---|---|
| D1 | FDR family = pooled 1d representatives per refit, not corpus-wide | The corpus-wide family can't be rebuilt per refit without a full recompute, and the ensemble consumes only pooled cells | V4 scope |
| D2 | Fitted-HMM features (`hmm_*`, `hmm_vol_*`) and todo 390's two columns excluded | Stored HMM labels carry full-sample parameters (todo 248); 390 is an unguarded division | Diagnostic variant |
| D3 | No weight aging | Now also production (todo 408, removed 2026-09-24); kept here because the 2026-09-22 champion was 1/n | Uniform-weight variant |
| D4 | No present-day status filter | Status is decided with later data | Section 5 |
| D5 | Covariance fitted on rows up to the IC window end | Now also production (todo 409, fixed 2026-09-24) | None needed |
| D7 | IC shrinkage prior from the refit's pooled rows only (V4b 2026-09-24: identical to production at the current window, since per-symbol 1d rows carry no `ic_sharpe_hac`) | Production's `(group_name, regime, tf)` bucket mixes per-symbol rows (~99% of an equity label's bucket at 1d, e.g. `high_bear` 143,100 vs 1,160); a per-symbol pass per refit is a large multiple of the IC compute | V4b |
| D6 | Cluster representatives chosen correctly | Now also production (todo 410, fixed 2026-09-24); earlier stored rows carry the bug | None needed |

## 14. Residual biases that remain

- **Survivorship and present-day routing in the pooling universe.** All symbols are listed today
  (todo 376), and equity-group membership comes from present-day tags.
  Delisted names would have joined the pooled IC; their absence likely inflates the IC of
  distress-sensitive features. Direction: optimistic. Not fixable in this phase.
- **Design-time snooping.** Feature definitions and APR values were chosen by people who had
  seen the full history. The walk-forward can't remove that; it's why ACT also needs the holdout
  sign and why N_tested is counted.
- **Sleeve data depth.** TLT's 1d history starts in 2017 in this corpus (listed since 2002);
  the point-in-time coverage filter admits it when its trailing window fills, so it's absent from
  about the first four out-of-sample years.
- **Holdout viewed once in aggregate** (section 2); hence sign-check-only use.
- **Equity-learned weights for non-equity assets.** Production learns weights from the equity
  group's pooled IC, stratified by U.S. equity breadth/vol regimes, and applies them to GLD, TLT
  and the rest of the sleeve. The harness reproduces this faithfully; an
  asset-class-aware variant is a separate future test that would count toward N_tested.

## 15. Build order

1. File todos 409 (trainer covariance over all bars), 408 (wall-clock weight aging) and 410
   (FDR representative selection); promote todo 390 to P1. Done 2026-09-24.
2. Stratum-fit extraction (c6750d700) and the shared representative helper (7fa346137).
   Done 2026-09-24.
3. Portfolio primitives moved to `src/intelligence/portfolio/weighting.py`, with the coverage fix
   (no zero-filled gaps). Done 2026-09-24.
4. `panel_null.py` with tests. Done 2026-09-24 (edb555a11).
5. Harness S0-S4 with synthetic end-to-end tests; run V2, V3. Code done 2026-09-24 (harness plan execution record); V2/V3 runs wait for the 178 recompute.
6. HMM-feature audit, deprecated-feature decision, S0 snapshot, V4, V5 at T = 2025-12-24.
7. Commit the section 12 addendum. The pre-registration is frozen here.
8. S1-S4 once. Commit the result JSON and the ledger row.
9. S5 holdout read. Commit the final token.
10. `/simplify`, `/code-review`, independent review of the verdict doc (AGY; Codex when its quota
    resets).

Steps 2-4 are ordinary engineering on shared code and follow the Done-Coding SOP. Nothing in
steps 1-7 computes an out-of-sample number.

## 16. Review record

AGY adversarial review, 2026-09-24, verdict "not freeze-ready". Every code claim was checked
before disposition.

| # | Finding | Disposition |
|---|---|---|
| 1 | Rerunning calibration per shift would let a drifting asset look like timing; freeze calibration at real-run values | Rejected. A permutation test must apply the same statistic, calibration included, to each shifted pairing. Under H0 the real run's calibrated IC is as noisy as the shifted runs', so drift earns nothing systematic in either; freezing calibration at the real values would leak real alignment into the null. Section 1 wording tightened |
| 2 | The diagnostic's 504-session warmup silently removes 2013-2014 | Accepted, verified (`_INITIAL_WARMUP_BARS = 504`). Refits start 2011 so trading covers 2013-2025 |
| 3 | V4 can't pass: production pools the equity group only, broadcast cells omitted, representative bug | Accepted, all three verified. Universe = equity group via production routing; broadcast cell path reused; V4 excludes FDR fields; the representative bug is real and corpus-wide (681,851 rows, 2,842 false `passes_fdr`), filed P0 as todo 410 |
| 4 | The cell function hardcodes `_FEATURE_NAMES` | Accepted. Full matrix always passed; exclusions go through the mask |
| 5 | FAIL and PASS not disjoint | Accepted. "Qualifying arm" defined once; FAIL = none qualify |
| 6 | Power table showed the 50%-power effect size | Accepted. 50% and 80% columns |
| 7 | Holm is conservative for co-permuted correlated arms | Accepted. Westfall-Young max-statistic |
| 8 | Full per-shift rerun is expensive | Partly accepted. Covariance computed once (return-only); calibration per shift in a numba kernel, cost measured before freeze. Not by adopting finding 1's fixed calibration |
| 9 | Per-scale purge ambiguous | Accepted. Trim at h=1, per-scale `complete_mat` |

