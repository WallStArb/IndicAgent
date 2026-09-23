# Correlation regime and single-name breadth: design

Author: Claude Opus 5.5
Date: 2026-09-23
Status: design, pre-registration draft. Nothing here has been measured yet; every threshold
below is fixed before data is seen and must not move after.

## The question

Does adding single-name US equities (Russell 2000 and the lower half of the S&P 500) buy
measurable edge, and if so, when?

Phase 174 answered a narrower question: adding single names does not produce decorrelated raw
returns. Its pilot (40-name unbiased down-cap draw) averaged 0.30 pairwise correlation
unconditionally and 0.43 in `high_bear`, and no regime cell in either the pilot or the 117-name
book got below 0.14. The cause is shared market beta.

The same data shows the thing this design is built on: correlation is strongly regime-dependent.
On the existing 117-name book:

| Regime | Avg pairwise correlation | n_eff |
|---|---|---|
| `mid_bull` | 0.14 | 6.7 |
| `low_bull` | 0.17 | 5.6 |
| `low_neutral` | 0.20 | 4.9 |
| unconditional | 0.32 | 3.1 |
| `high_bear` | 0.48 | 2.1 |

Source: `docs/research/phase174-down-cap-correlation-gate-verdict.md`.

Single names are not worthless. Their value should be concentrated in low-correlation periods,
when stock-specific dispersion is high and cross-sectional ranking has room to work. In
high-correlation periods everything moves together and the cross-asset book carries the
diversification. That is a falsifiable claim, and it decides whether an expensive data purchase
is worth making. So it is tested first, on data already in hand, before any money is spent.

## What a Renaissance review demands of this

1. **Data before models.** No measurement on a universe that could not have been known at the
   time. No stock-picking study on a survivorship-biased universe.
2. **One primary hypothesis, fixed in advance**, with its test statistic, its null, and its
   pass/fail thresholds written down before the first number is computed. Secondary analyses are
   labeled secondary and cannot rescue a failed primary.
3. **An explicit null for every claim.** A regime that "sharpens IC" must beat the same regime
   labels shifted in time, which keeps their persistence and base rates but destroys their
   alignment with the returns.
4. **Name every channel through which a spurious result could appear**, and close each one by
   construction rather than by argument.
5. **The minimum mechanism that answers the question.** Anything not needed for the primary
   hypothesis is deferred.

## Hidden-bias register

Each row is a way this study could produce a confident, wrong answer, and how the design closes it.

| # | Bias | How it would fool us | Closed by |
|---|---|---|---|
| B1 | Beta contamination of rank IC | In high-correlation periods returns are mostly beta, so a cross-sectional rank of returns is mostly a rank of beta times the market move. Any feature correlated with beta (volatility, momentum, size) then "predicts" with a sign that flips with market direction. The IC gap between low- and high-correlation regimes would be manufactured by the target, not the features. This bias is aligned exactly with the variable under study, so it is the most dangerous one here. | Measure on a market-residualized forward return (D3). Raw-return IC is reported alongside for comparison, never used for the verdict. |
| B2 | Look-ahead in the regime label | A percentile rank over the full sample uses future data to classify the past. | The correlation state at date t uses returns through t-1 only. Percentiles are expanding-window with a 252-day burn-in; nothing before the burn-in is labeled. |
| B3 | Survivorship in the regime input | If correlation is computed from today's surviving stocks, the past regime is estimated from firms that were selected for having survived. | The state is computed from a fixed panel of sector ETFs, not from stocks (D1). ETFs have no survivorship and constant membership. |
| B4 | Non-synchronous trading (Epps effect) | Illiquid small caps print stale prices, which mechanically lowers measured correlation. That would make a small-cap universe look diversified and bias the state toward "low correlation" whenever illiquid names dominate. | Liquid sector ETFs as the state input (D1). The small-cap universe is used only in stage 2, with a liquidity floor (D6). |
| B5 | Regime is just volatility | High correlation co-moves with high volatility. A "correlation" effect may be the existing `regime_volatility` in disguise. | Orthogonality test (H2) inside volatility strata, pre-registered as its own verdict. |
| B6 | Searching over window length or thresholds | Trying 21/63/126-day windows or several cut points and keeping the best one is a hidden multiple-comparison. | One window (63 trading days) and one cut (terciles), fixed here. The absorption ratio is a single, labeled robustness check, not a second chance. |
| B7 | Survivorship in the stock universe | Delisted names, disproportionately the extreme movers, are absent. Every IC measured on today's constituents is conditioned on survival. | Stage 2 is blocked until a point-in-time source with delisted names exists (todo 376). Stage 1 uses the existing universe and states the limitation. |
| B8 | Look-ahead in universe membership and classification | Using today's Russell 2000 list, or today's sector labels, for 2010 selects on outcomes that were not known then. | Stage 2 requires point-in-time membership and point-in-time sector (todo 384). |
| B9 | Selecting names on the statistic under test | Choosing names for "low correlation" and then measuring their correlation benefit is circular. | Stage 2 draw is mechanical and stratified on sector, size and liquidity only, never on measured correlation or IC. |
| B10 | Multiple comparisons across features, tfs and regimes | Many cells, some of which pass by chance. | The primary verdict is one statistic aggregated over the pre-registered feature set, with its own null distribution (H1), not a count of passing cells. |
| B11 | Autocorrelated regimes and overlapping returns | Persistent regimes and overlapping forward windows shrink effective N. Naive standard errors overstate significance. | The null is a circular block shift of the regime series, which keeps its persistence. Per-cell CIs already use circular block bootstrap. |
| B12 | Holdout leakage | Tuning on the out-of-sample period. | Training window clamped at `alpha.validation.oos_start` = 2025-12-24, as in Phase 176. The holdout is not looked at until the in-sample verdict is written. |
| B13 | Noise inflating absolute IC | The cross-sectional universe grows from a handful of symbols in 2006 to 233, and correlation regimes cluster in time, so the terciles differ in average cross-section size. `|IC|` is biased upward by noise, most in the noisier tercile, so an absolute-value statistic can manufacture a difference from sample size alone. | H1 uses signed IC in each feature's tradeable direction (the sign of its unconditioned IC), which has no noise-driven upward bias, and reports the median daily cross-section size per tercile. |
| B14 | Beta estimation error left in the residual | With an estimated beta, the residual still carries (beta error) x (market return). That leftover is largest exactly when the market term dominates, in high-correlation periods, so residualization is weakest where it matters most. | Shrink each beta toward 1 (Blume's fixed weights, D3). Diagnostic per tercile: cross-sectional correlation of the residual target with trailing beta. If it is materially non-zero in the high tercile, the verdict carries that caveat. |

## Design, stage 1: the correlation state and one test

Stage 1 uses only data already in the corpus. It needs no IBKR fetch and no purchase, and at the
post-todo-385 compute cost it is one ic_engine corpus run.

### D1. State input: a fixed sector-ETF panel

The nine original SPDR sector ETFs (XLB, XLE, XLF, XLI, XLK, XLP, XLU, XLV, XLY). All nine have
continuous daily history in `market_data_ohlcv_tradeable` since June 2006 and fixed membership.
XLRE (2015) and XLC (2018) are excluded: adding a series mid-sample changes what the statistic
measures at that date.

Why sectors rather than stocks: they carry no survivorship (B3) and no stale prices (B4), and
average pairwise correlation among sectors is the textbook measure of "one trade or many." Nine
series give 36 pairs, enough for a stable average over a 63-day window.

### D2. The statistic and the label

- `sector_corr_63d`: mean of the 36 pairwise Pearson correlations of daily close-to-close log
  returns over the 63 trading days ending at t-1. Causal (B2).
- `sector_corr_pct`: expanding-window percentile rank of `sector_corr_63d` among all prior
  values, with a 252-day burn-in; NULL during burn-in.
- Label: `low` below the 1/3 percentile, `high` above 2/3, `mid` between. Terciles, fixed (B6).
- Intraday bars on date t take date t's state; nothing from date t itself enters it.
- Robustness check, labeled secondary: absorption ratio (share of variance explained by the
  first principal component of the same 9x63 window). If it disagrees with the primary state's
  verdict, report the disagreement; it cannot overturn the primary result.

### D3. The target: market-residualized forward return

A new `forward_returns.return_type`:
`executable_open_to_open_resid_mkt = r_i - beta_i,t * r_SPY`. Here `r` is the existing executable
open-to-open return over the same horizon (SPY's over the identical window), and `beta_i,t` is
the OLS beta of daily returns against SPY over the 252 trading days ending at t-1
(point-in-time, causal), shrunk toward 1 as `0.67 * beta_ols + 0.33` (Blume's classical
weights, fixed here, not tuned; B14). Symbols with fewer than 252 prior daily returns get no
residual row and drop out of the residualized measurement rather than receiving a noisy beta.

This is the load-bearing decision of the whole design (B1). The primary verdict is computed on
the residualized target only. Raw-target IC is reported in parallel so the size of the beta
contamination is itself measured.

Market-only residualization first. Sector residualization needs a point-in-time sector
taxonomy (todo 384) and is deferred to stage 2.

### D4. Mechanism: reuse Phase 176, do not build a second path

Phase 176 already built conditioning on a persisted, market-wide column: a column on
`feature_vectors`, label derivation inside `ic_engine`, per-symbol stratification passes,
cross-sectional sub-cells by in-memory masking, `regime_scope` isolation from the ensemble
trainer, and a gate verdict. The correlation state is the second instance of that pattern.
Two instances justify extracting a contract (one parameterized conditioning path: column,
label rule, scope name), consistent with
`docs/research/stratification-dimension-unification.md`. They do not justify a third bespoke
branch. No new table, no HMM, no new service.

Pre-flight for this: extract the conditioning path once, with 176's earnings-season behaviour
as its regression fixture (its 176-08 output must reproduce bit-identically through the
generalized path before the new dimension is added).

### H1, primary: dispersion pays in low-correlation regimes

Feature set, fixed before measurement: every feature that passes corpus-level BH-FDR in the
unconditioned cross-sectional pass of the same run, on the residualized target, at the 1d tf.
1d is the gating tf, as in Phase 176; 1h is supporting evidence only.

Per feature `f`, let `s_f` be the sign of its unconditioned cross-sectional IC, and let
`IC_low(f)` and `IC_high(f)` be the mean of its daily cross-sectional rank ICs over the dates
in the low and high terciles (equal weight per date). Signed IC in the tradeable direction is
`s_f * IC`: a sign reversal between regimes counts against the hypothesis, as it would cost
money, instead of being hidden by an absolute value (B13).

Statistic: `D = median over the feature set of s_f * (IC_low(f) - IC_high(f))`, and, for
reporting only, `R = D / median over the feature set of s_f * IC_uncond(f)` (the size of the
regime gap relative to the typical unconditioned IC). A difference, not a ratio: it stays
well-behaved when the high-regime IC is near zero.

Null: recompute `D` with the tercile label series circularly shifted by a uniformly random
offset (at least 252 trading days from zero), 1000 draws. The shift keeps each tercile's size
and persistence and destroys its alignment with returns (B11). The feature set is fixed across
draws: it is selected on unconditioned IC, which does not depend on the labels, so selection
does not invalidate the null.

Verdict, pinned now:

- **PASS**: `D` above the 95th percentile of the null and `R >= 0.5` (the low-correlation
  tercile's tradeable IC exceeds the high tercile's by at least half a typical unconditioned IC).
- **FAIL**: `D` inside the null's 95% range, or `R < 0.2`.
- **WEAK**: anything else. Treated as FAIL for gating stage 2.
- **INSUFFICIENT_N**: fewer than 10 features in the set, or any tercile with fewer than 400
  1d dates.

Reported alongside, never used for the verdict: the same statistic on the raw target (the size
of the beta contamination, B1), per-tercile median cross-section size (B13), and the
per-tercile residual-vs-beta correlation (B14).

### H2, required for PASS to count: not volatility in disguise

Within each `regime_volatility` level, recompute `D` and `R` over the correlation terciles.
H1's PASS stands only if `R >= 0.3` with `D > 0` in at least two of three volatility levels
with enough N (at least 200 1d dates in both terciles within the level).
Otherwise the verdict is REDUNDANT: the effect is volatility, which the book already conditions
on (B5).

### What stage 1 decides

- **H1 PASS and H2 not REDUNDANT**: single-name breadth has regime-dependent value. Proceed to
  stage 2, and the correlation state becomes a candidate allocation input between the
  single-name and cross-asset books (shadow mode first).
- **FAIL or REDUNDANT**: do not buy survivorship-free data for single-name breadth on this
  argument. Record the verdict in `docs/research/construction-verdict-ledger.md`. The
  cross-asset book remains the breadth lever.

Stage 1 is measured on the existing 233-symbol universe, which carries B7. Stated plainly: a
stage-1 PASS is necessary, not sufficient. It says the mechanism exists in survivors. It does not
say how large it is in the full population.

## Design, stage 2: the breadth expansion (gated on stage 1)

Not scoped in detail until stage 1 passes. The fixed requirements:

- **D5. Point-in-time universe with delisted names (todo 376).** IBKR cannot serve delisted
  history, so this needs a vendor decision (historical index membership plus delisted OHLCV
  and corporate actions). The fallback is a forward-only universe, which is clean but only
  accumulates evidence from its start date. This is a cost decision for the user, made after
  stage 1, not before.
- **D6. Mechanical stratified draw.** Population: Russell 2000 plus S&P 500 constituents below
  the index median market cap, point-in-time. Strata: point-in-time sector (todo 384) x size
  tercile. Liquidity floor on trailing median dollar volume, as a data-integrity rule against
  stale prints (B4), not a cost gate (per the standing directive that execution costs never gate
  the edge search). The draw size is set from measured compute and a stated minimum detectable
  IC difference, not from a target count.
- **D7. Sector-residualized target** added once the taxonomy exists, reported alongside the
  market-residualized one.
- **Primary stage-2 question:** does the stage-1 effect hold, and at what size, on the
  survivorship-free expanded universe, with the same statistic, null and thresholds?

## Deliberately not built

- No HMM for correlation. A percentile-rank state is transparent, causal and cheap. The standing
  rule on HMM regime candidates (null-arm first) is kept either way.
- No implied-correlation data purchase (the CBOE implied correlation indices). The realized
  sector state answers the question; implied data can be a later robustness check.
- No window or threshold search.
- No second conditioning code path.
- No universe purchase before stage 1 says it is worth one.

## Sequencing

1. Phase 176-08 finishes. Nothing is written to `feature_vectors` or `forward_returns` until then.
2. Build: the residualized return type (D3), the sector correlation state (D1-D2) as a broadcast
   `feature_vectors` column, and the generalized conditioning path (D4, verified bit-identical
   on 176's earnings-season output).
3. One ic_engine corpus run. At the todo-385 cost this is hours, not days.
4. Write the H1/H2 verdict against the thresholds above. Holdout untouched.
5. Only then: the stage-2 data decision.

## Open items this depends on

- Todo 376 (survivorship sourcing): blocks stage 2 only.
- Todo 384 (classification hierarchy): blocks D6 strata and D7 only.
- Data freshness: as of 2026-09-23, 109 of 273 symbols have 1d bars frozen at 2026-08-10,
  including SPY and all nine sector ETFs. Historical measurement is unaffected. Any live use of
  the state needs current sector-ETF bars, so this has to be fixed before shadow deployment.
