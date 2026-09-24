# Correlation regime and single-name breadth: design

Author: Claude Opus 5.5
Date: 2026-09-23 (v1), revised 2026-09-24 (v2, after adversarial review)
Status: pre-registration draft, v2. Nothing here has been measured. Every choice below is fixed
before data is seen and must not move after. v2 incorporates an independent adversarial review
(AGY, 2026-09-24); the accepted and rejected findings are listed at the end.

## The question

Does adding single-name US equities (Russell 2000 and the lower half of the S&P 500) buy
measurable edge, and if so, when?

Phase 174 showed that adding single names does not produce decorrelated raw returns: its 40-name
down-cap pilot averaged 0.30 pairwise correlation unconditionally and 0.43 in `high_bear`, because
shared market beta dominates (`docs/research/phase174-down-cap-correlation-gate-verdict.md`).
The same data shows correlation is strongly regime-dependent. On the existing 117-name book:

| Regime | Avg pairwise correlation | n_eff |
|---|---|---|
| `mid_bull` | 0.14 | 6.7 |
| `low_bull` | 0.17 | 5.6 |
| `low_neutral` | 0.20 | 4.9 |
| unconditional | 0.32 | 3.1 |
| `high_bear` | 0.48 | 2.1 |

Hypothesis: single-name cross-sectional ranking pays when correlation is low (dispersion is high)
and not when it is high. If true, single-name breadth is worth buying data for, conditioned on
regime. If false, it is not, and the cross-asset book stays the breadth lever. This is tested
first on data already in hand, as a standalone research script, before any money is spent or any
production code changes.

## Relation to closed verdicts

Two residualization-adjacent constructions are closed DEAD in
`docs/research/construction-verdict-ledger.md`, and this design re-opens neither:

- **statistical_factor_residual** (closed 2026-09-01) residualized a *feature* against its top-K
  statistical factors to raise its IC. It did not.
- **Single-security alpha gating** (closed 2026-09-03) asked whether `alpha_score` works as a
  per-security time-series signal. Raw, it is a common-factor bet; residualized, it failed BY-FDR.

Here residualization is applied to the *target*, only as measurement hygiene, to remove the
market and sector terms that would otherwise manufacture the regime difference under test
(B1, B15). No claim is made that residualizing improves IC, and no per-security signal is gated.

## Principles

1. Data before models: no measurement on a universe that could not have been known at the time.
2. One primary hypothesis per question, with statistic, null and thresholds fixed in advance.
   Secondary analyses cannot rescue a failed primary.
3. An explicit null for every claim.
4. Every channel to a spurious result is named and closed by construction.
5. The minimum mechanism that answers the question. Stage 1 is a script, not infrastructure.

## Hidden-bias register

| # | Bias | How it would fool us | Closed by |
|---|---|---|---|
| B1 | Market-beta contamination of rank IC | In high-correlation periods returns are mostly beta, so ranks of returns are mostly ranks of beta times the market move, and beta-correlated features "predict" with a sign that flips with the market. | Target residualized against SPY (D3). Raw-target results reported alongside, never used for a verdict. |
| B15 | Sector contamination of rank IC | A low sector-correlation state is by definition a period when sectors diverge, so a market-only residual still carries each name's sector move, and any sector-correlated feature shows IC from unhedged sector bets, not stock selection. This is aligned exactly with the state variable. | Target residualized jointly against SPY and the name's own SPDR sector ETF (D3). Names without a mappable sector are excluded. |
| B2 | Look-ahead in the state | Full-sample percentiles or same-day data classify the past with the future. | The state at date t uses returns through t-1 only, and is used as a raw level, not a percentile (D2). |
| B17 | Non-stationarity | Anomaly decay, universe growth (a few names in 2006, ~128 now) and crisis clustering make any time-shuffled null too narrow, and an expanding percentile labels the same correlation "high" in 2007 and "low" in 2011. | Continuous raw state with year fixed effects in the primary regression (H1); the shift null runs within epochs only (secondary). |
| B3 | Survivorship in the state input | A state computed from today's surviving stocks estimates past regimes from firms selected for survival. | The state comes from a fixed panel of sector ETFs (D1). |
| B4 | Non-synchronous trading (Epps effect) | Stale prints in illiquid names mechanically lower measured correlation. | Liquid sector ETFs as the state input (D1); liquidity floor in stage 2 (D6). |
| B5 | The state is just volatility | High correlation co-moves with high volatility. | H1 regresses IC on both states jointly; the correlation coefficient must survive the volatility term. |
| B6 | Searching over windows, cuts, horizons or features | Hidden multiple comparisons. | One window (63 days), no cuts (continuous state), one horizon (1d `fast`), one fixed feature list, all named here. |
| B16 | Selecting features on the same data | Features chosen for significance on this sample, and possibly none surviving on a residualized target (0/231 in the closed single-security residual test). | A fixed, pre-registered feature list chosen on economic grounds before any measurement (D4). |
| B7 | Survivorship in the stock universe | Delisted names, disproportionately extreme movers, are absent. | Stage 2 is blocked on a point-in-time universe with delisted names (todo 376). |
| B18 | Survivorship interacting with the regime | In low-correlation periods idiosyncratic divergence dominates, and the names that diverged downward into delisting are missing, so survivorship can manufacture a low-correlation IC advantage by itself. | A stage-1 PASS authorizes only the stage-2 data decision. It never authorizes allocation or shadow use. Stage 2 repeats the test on a survivorship-free universe. |
| B8 | Look-ahead in membership and classification | Today's index lists or sector labels applied to the past. | Stage 2 requires point-in-time membership and sector (todo 384). Stage 1 uses current sector labels on survivors and says so. |
| B9 | Selecting names on the statistic under test | Circularity. | Stage 2 draw is mechanical, stratified on sector, size and liquidity only. |
| B11 | Autocorrelated state and overlapping returns | Effective N smaller than it looks. | Newey-West HAC standard errors (lag fixed at 20 trading days); 1-bar horizon has no overlap. |
| B13 | Noise inflating absolute IC | Absolute values turn sampling noise into apparent strength. | Signed IC in each feature's pre-registered economic direction (D4). |
| B14 | Beta estimation error in the residual | The residual still carries (beta error) x (factor return), largest when factor moves are large. | Diagnostic: daily cross-sectional correlation of the residual with trailing beta, reported by state level. |
| B12 | Holdout leakage | Tuning on the out-of-sample period. | Sample ends at `alpha.validation.oos_start` = 2025-12-24. The holdout is read only after the in-sample verdict is written. |

## Stage 1: a standalone research script

`scripts/research/correlation_breadth_stage1.py`. It reads existing tables only
(`market_data_ohlcv_tradeable` 1d, `feature_vectors` 1d, `forward_returns` 1d
`executable_open_to_open`, `instruments`, `instrument_tags`). No migrations, no `ic_engine`
changes, no new columns. Production infrastructure is built only if stage 1 passes. Deterministic:
fixed seed for every random draw, recorded in the output.

### D1. State input: a fixed sector-ETF panel

The nine original SPDR sector ETFs (XLB, XLE, XLF, XLI, XLK, XLP, XLU, XLV, XLY), continuous in
`market_data_ohlcv_tradeable` 1d since June 2006 with fixed membership. XLRE (2015) and XLC (2018)
are excluded; adding a series mid-sample changes what the statistic measures.

### D2. State variables

- `corr_t`: mean of the 36 pairwise Pearson correlations of the nine ETFs' daily close-to-close log
  returns over the 63 trading days ending at t-1. Raw level, no percentile (B2, B17).
- `vol_t`: annualized realized volatility of SPY's daily log returns over the same 63 days ending
  at t-1. Used only as the control in H1 (B5).
- `conc_t` (H3 only): SPY's 63-day log return minus RSP's over the same window ending at t-1.
  Positive means cap-weighted is beating equal-weighted, meaning narrow, mega-cap-led leadership.

### D3. Target: market- and sector-residualized next-day return

For single name i with sector ETF `S(i)`, on each date t:

`u_i,t = r_i,t - b_i * r_SPY,t - c_i * r_S(i),t`

`r` is the 1d `fast` (1-bar) `executable_open_to_open` return from `forward_returns`, and the SPY
and sector ETF returns come from the same table over the identical window. `b_i` and `c_i` are
joint OLS coefficients of i's daily returns on SPY and `S(i)` over the 252 trading days ending at
t-1. No shrinkage. A name enters on a date only with 252 prior daily returns.

Sector map: `instruments.contract_details->>'sector'` to SPDR ETF (technology->XLK,
healthcare/healthcare_biotech->XLV, financials->XLF, industrials/industrials_*->XLI,
consumer_discretionary->XLY, consumer_staples->XLP, energy/energy_midstream->XLE,
utilities/utilities_water->XLU, materials_*->XLB, real_estate->XLRE only after its inception, else
excluded, communication_services->XLC only after its inception, else excluded). Names whose sector
is empty or not in this map are excluded, and the count is reported.

### D4. Universe and feature list (fixed now)

- Universe: symbols tagged `single_name_equity` (human source) that have `feature_vectors` 1d rows,
  are not ETFs, and have a mapped sector on that date. About 128 names today; the daily count is
  reported.
- Features, each with its pre-registered direction `s_f` (the sign of the conventional effect):
  `momentum_z_fast` (+1), `momentum_z_mid` (+1), `range_position` (-1, short-horizon reversal),
  `bar_close_pos` (-1), and the volume and volatility features named in 176-01's 57-feature sweep
  that are present in `FeatureVector` at run time, with the direction taken from their unconditioned
  sign in the Phase 173 corpus run, which predates this design. The exact list and signs are frozen
  into the script as a constant, committed before the script is first run, and the commit SHA is
  recorded in the verdict.

### H1 (primary): cross-sectional IC rises as correlation falls

For each feature f and date t, `IC_f,t` is the Spearman rank correlation across the day's
universe between the feature value at t and `u_i,t`. Pooled across features as
`y_t = mean_f( s_f * IC_f,t )`, the average signed IC in the pre-registered direction.

Regression, on dates from the first date with at least 30 names through 2025-12-24:

`y_t = a + g * corr_t + h * vol_t + year fixed effects + e_t`

Newey-West HAC standard errors with 20 lags. Effect size `E = g * (P80(corr) - P20(corr))`: the
change in average signed IC moving from a high-correlation day (80th percentile) to a
low-correlation day (20th percentile), in IC units.

Verdict, pinned now:

- **PASS**: `g < 0` with HAC one-sided p < 0.025, and `|E| >= 0.005` (half a point of IC per
  feature, against typical residual cross-sectional ICs of about 0.01-0.03).
- **FAIL**: p >= 0.10, or `g >= 0`.
- **WEAK**: anything else. Treated as FAIL for gating stage 2.
- **INSUFFICIENT_N**: fewer than 750 dates with at least 30 names.

The alpha of 0.025 reflects two pre-registered primary tests (H1 and H3), Bonferroni.

Secondary, reported but never gating: the same regression without the volatility term; the same
without year effects; per-feature coefficients; a within-epoch circular-shift null (shift `corr_t`
within each calendar-year block, 1000 draws, seed fixed); the raw-target version (size of B1/B15
contamination); the B14 diagnostic; and the regression with `corr_t` replaced by the daily
cross-sectional return dispersion of the universe itself (the reviewer's proposed state, reported
for comparison only because it carries B3/B4).

### H3 (primary, independent): concentration hurts cross-sectional ranking

Same `y_t`, same controls, regressor `conc_t` in place of `corr_t` (with `corr_t` added as a
control):

`y_t = a + k * conc_t + g * corr_t + h * vol_t + year fixed effects + e_t`

PASS: `k < 0` with HAC one-sided p < 0.025 and `|k * (P80(conc) - P20(conc))| >= 0.005`. FAIL and
WEAK as H1. H3 has its own verdict and cannot rescue H1. Reported alongside: the fraction of dates
where the concentration and correlation states disagree (high concentration with low correlation),
and `y_t` in that cell.

### What stage 1 decides

- **H1 PASS**: stage 2 is worth scoping, meaning the data-sourcing decision for a survivorship-free
  universe (todo 376) goes to the user with this result attached. Nothing else changes: no
  allocation use and no shadow deployment of the state on the strength of a survivor-only result
  (B18).
- **H1 FAIL or WEAK**: no data purchase for single-name breadth on this argument. The verdict goes
  into `docs/research/construction-verdict-ledger.md`. The cross-asset book remains the breadth
  lever.
- **H3** is reported on its own; a PASS makes concentration a candidate conditioning variable for
  any later single-name work, under the same survivorship caveat.

## Stage 2 (only after an H1 PASS)

Scoped after stage 1, with these fixed requirements: a point-in-time universe with delisted names
and corporate actions (todo 376; IBKR cannot serve delisted history, so this is a vendor decision
for the user); a mechanical draw from the Russell 2000 plus S&P 500 constituents below index-median
market cap, stratified by point-in-time sector and size, with a trailing median dollar-volume floor
as a data-integrity rule against stale prints (not a cost gate); point-in-time sector labels
(todo 384); and the identical H1/H3 tests, statistics and thresholds. Production infrastructure
(a residualized `forward_returns` type, a conditioning path in `ic_engine`) is built only then.

## Deliberately not built

No database changes, no `ic_engine` changes and no new service for stage 1. No HMM. No terciles or
percentiles. No window, cut, horizon or feature search. No implied-correlation data purchase. No
absorption-ratio variant. No universe purchase before stage 1 says it is worth one.

## Sequencing and prerequisites

1. Phase 176-08 finishes (it holds `feature_vectors`/`forward_returns` stable until then).
2. Freeze and commit the feature list (D4), then write and run the script.
3. Write the H1/H3 verdicts against the thresholds above; holdout untouched.
4. Fix before any live use of the states: SPY, RSP and all nine sector ETFs have no 1d bars after
   2026-08-10 as of 2026-09-24 (catch-up backfill in progress). Historical measurement through
   2025-12-24 is unaffected.
5. Data fix found while drafting: `instruments` labels RSPG `consumer_staples`; RSPG is Invesco's
   S&P 500 Equal Weight Energy ETF (formerly RYE).

## Review log

v2 changes from the adversarial review (AGY, 2026-09-24):

- Accepted: joint market-plus-sector residualization (the review's most important finding; v1's
  market-only residual would have measured sector timing); stage 1 as a standalone script with no
  infrastructure; replace the ratio gate with an absolute effect size and HAC inference; test
  orthogonality to volatility by joint regression instead of starved bivariate cells; raw
  continuous state with year fixed effects instead of an expanding percentile; bind to one horizon;
  a stage-1 PASS never authorizes allocation or shadow use (survivorship-regime interaction); plain
  OLS beta instead of Blume shrinkage; a fixed, pre-registered feature list instead of same-run
  FDR selection; drop the absorption ratio.
- Rejected as primary: replacing the sector-ETF state with cross-sectional return dispersion of the
  single-name universe. Dispersion computed on today's survivors carries the survivorship and
  stale-price biases (B3, B4) that the ETF panel was chosen to avoid. It is reported as a secondary
  comparison instead.
- Not accepted as stated: that the shift null is invalid because selection used unconditioned IC.
  A null that shuffles labels against a label-independent feature set is valid conditional on that
  set. The fix adopted (a fixed list) removes the question anyway.
