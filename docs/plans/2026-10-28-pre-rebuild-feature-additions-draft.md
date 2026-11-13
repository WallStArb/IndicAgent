# Pre-rebuild feature additions

**Status:** executed and condensed 2026-11-13. The decided add-list below landed in the 584 batch
(2026-11-03): the implementation spec at the bottom is verbatim in
`src/intelligence/features/kernels/residual.py`, `distribution.py` and `dividend.py`, which cite
it by item number; do not renumber it. This doc now holds only what is still live for todo 558:
the stored-column rule, the candidate lists, and the open items. The method narrative, findings
pass and both review passes (indicagent-9f 2026-10-31 PM-level, indicagent-2c 2026-11-01 rigor
pass) are cut; their outcomes are the pin-downs inside the spec. Full pre-condensation text: git
history, `1a36f2003`.
**Origin:** mapped 2026-10-28 from the owner's question "do we need new features, factors or
signals"; decided at PM level 2026-10-31; owner retains veto.

## The stored-column rule

A stored column is a single-name function of that name's own bars and fixed macro inputs, needed
by a queued family. Anything cross-sectional, residualized or sector-relative stays in the
research layer (S0 kernels, S1 target), which is why the `rank_z` trio was dropped in 186-24 and
why residual momentum is a research construction. A column added without a family waiting for it
is not a look, but it adds nothing until a family tests it, so rebuild passes are spent only on
columns with a named consumer.

## Add-list (decided; all ten landed 2026-11-03)

`residual.py` carries items 1 to 5, `distribution.py` items 6 to 9, `dividend.py` item 10. All
ten entered `concept_registry` as `candidate` (domain `feature`); promotion to `active` only when
a family prereg names the column.

| Column | Consumer rationale | Notes |
|---|---|---|
| `idiosyncratic_volatility` (residual std of daily returns vs the fixed market series, rolling) | Ang et al. idio-vol premium; first feature family names it | Sibling of `equity_beta_z`: same regression, residual std instead of slope |
| `market_residual_return` + `market_residual_z` + `market_residual_lag1_acf` | Stat arb spread family (ledger section 2, todo 559 prereg) | Market-only residual stored by design; sector residual stays in S1 (point-in-time classification) |
| `residual_beta_stability` (rolling change in market beta) | Factor-drift risk measured, not assumed; guards the residual families | Cheap sibling of the beta kernel |
| `max_daily_return` (MAX effect, declared window) | Lottery-demand discount, Bali et al.; strong cross-sectional prior | One window only; more windows is overfitting before evidence |
| `max_drawdown` (rolling window) | Drawdown is a distinct risk state from volatility; regime segmentation input | Declared memory like every other rolling column |
| `downside_deviation` (rolling, target = 0) | Downside semivol asymmetry; complements `vol_asymmetry_z` | NaN below warmup, never zero |
| `size_proxy` (rolling mean log dollar volume) | Size factor for the residual model without shares outstanding | Distinct from `dollar_vol_z` (a z-score); store the level's log, not a rank |
| `dividend_yield` + `days_to_ex_dividend` | Corporate-action event family; data exists in `dividend_events_reconciled` | Outside `dividend_event_coverage` the value is unknown: NaN, never zero (the dividends rule) |

`days_to_ex_dividend` did NOT enter the pass: `dividend_events` and
`dividend_events_reconciled` carry ex-date, amount and prev-close only, with no
declaration/announcement timestamp, so "days to the next ex-date" cannot be computed at t without
reading the future. It stays research-layer-only until the dividend layer records availability
times.

## Research-layer first, no stored column

OU half-life and equilibrium sigma of the residual (the Avellaneda-Lee s-score machinery) and
residual reversal interactions (volume shock, illiquidity, regime): composites tested through the
research kernels and the S7 combiner, promoted to storage only after a family verdict earns it
(the 550-552 pattern). Rolling PCA/cointegration: layer rules already exclude them (the pairs
verdict is DEAD). The stored `*_product` interaction columns are the pattern the registry already
carries and its `nonlinear_interaction_combiner` result is inconclusive, so more of them buy
nothing until that is settled.

Blocked on a data source, not a rebuild matter: fundamentals (size, value, quality, earnings
surprise; a source decision needs the same measured-basis treatment as the Databento study) and
short interest/borrow (todo 438 is forward-only capture).

## Open items (todo 558)

1. Lane owners decide which add-list members the first-batch family names; any column no family
   names stays `candidate` (built, never `active` until consumed).
2. Fill `redundancy_group` (empty for all 302 features at review time) from measured correlations
   on the rebuilt table, not construction intuition.
3. Measure `ret_acf1_z` vs `ret_autocorr_1` correlation before any dedup judgment; the rule is
   never to drop data that could carry signal.
4. Confirm the three never-computed `rank_z` registry rows retire through ConceptRegistryService
   with the rebuild pass (todo 421's registry half).

## Implementation spec (584 item 8, session indicagent-ef, 2026-11-03)

The pinned definitions below resolve the five pin-downs; the kernel modules carry the same text.
Reference: Avellaneda & Lee 2010 (Quantitative Finance 10(7) 761-782) is the consumer paper for
the residual family; its s-score machinery (OU half-life, equilibrium sigma) stays
research-layer-first as decided above.

Scope: ten stored columns this pass. `days_to_ex_dividend` does NOT enter:
`dividend_events` and `dividend_events_reconciled` carry ex-date, amount and prev-close only,
with no declaration/announcement timestamp, so "days to the next ex-date" cannot be computed at
t without reading the future (pin-down 3). It stays research-layer-only until the dividend
layer records availability times.

Modules (all new, `src/intelligence/features/kernels/`):

- `residual.py` - the market-residual family, sibling of `kernels/macro.py`'s beta path. One
  builder over the daily reference grid, one grid kernel, one row-grid pass-through with
  `ext_*` DAILY_ASOF_CLOSE externals, exactly the `factor_beta_daily`/`build_symbol_beta_series`
  shape. The beta inside the residual is THE equity beta: the same rolling OLS estimator and the
  same `feature.factor_beta.window` seed, never a second beta definition.
- `distribution.py` - the single-name return-distribution and scale columns.
- `dividend.py` - `dividend_yield`.

Definitions (daily grain, broadcast to every timeframe by date, the beta cadence contract; the
market series is SPY daily log returns, pin-down 2; all windows full-window only, NaN until
filled, zero-spread z NaN):

1. `market_residual_return[t]` = r_sym[t] - beta[t] * r_spy[t], where beta[t] is the trailing
   `feature.factor_beta.window` OLS slope over returns ending at t (var_spy <= 1e-12: NaN). NaN
   at every date for SPY (self-regression is degenerate, the equity_beta_z rule).
2. `idiosyncratic_volatility[t]` = sample std (ddof=1) of the residual over the trailing
   `feature.idiosyncratic_volatility.window` (default 21, [conventional] monthly, Ang et al.
   2006; unannualized).
3. `market_residual_z[t]` = trailing time-series z of the name's own residual series over
   `feature.market_residual.z_window` (default 252, [conventional] one trading year), pin-down
   1: cross-sectional standardization never happens in storage.
4. `market_residual_lag1_acf[t]` = lag-1 autocorrelation of the residual over
   `feature.market_residual.lag1_acf_window` (default 63, [initial_estimate] one quarter).
5. `residual_beta_stability[t]` = sample std (ddof=1) of the rolling beta over
   `feature.residual_beta_stability.window` (default 60, [initial_estimate]); pin-down 4
   resolved to the dispersion estimator, not beta-minus-lag-k: no sign ambiguity, one window,
   composes with the beta history the kernel already accumulates.
6. `max_daily_return[t]` = max daily log return over `feature.max_daily_return.window` (default
   21, [conventional] monthly, Bali et al. MAX).
7. `max_drawdown[t]` = 1 - min over the trailing `feature.max_drawdown.window` (default 252,
   [conventional]) grid dates of close[j] / max(close within the window up to j). Close-based,
   price-only (pin-down 5): the total-return adjustment is a research-layer concern via
   `panel.total_return`. Stored in [0, 1]; 0.0 is a measured state (new high held through the
   window). Lead ruling 2026-11-03: the earlier `Stored <= 0` contradicted the formula (every
   ratio is <= 1, so 1 - min is in [0, 1]); the formula stands, matching
   research/evaluate.py's positive-magnitude max_drawdown.
8. `downside_deviation[t]` = sqrt(mean(min(r, 0)^2)) over `feature.downside_deviation.window`
   (default 252, [conventional]); target 0; 0.0 is measured (no negative return in the window).
9. `size_proxy[t]` = mean over `feature.size_proxy.window` own-grid bars (default 63,
   [initial_estimate]) of ln(close * volume); dollar volume <= 0 is NaN, and the column runs
   per volume-basis segment (it reads the volume level). Stored at the row timeframe like every
   own-bars column; the level is a scale, not comparable across timeframes.
10. `dividend_yield[t]` = sum of dividend_events amount over the trailing
    `feature.dividend_yield.window` (default 252, [conventional] trailing twelve months) grid
    dates divided by close[t]; one event per ex-date, Yahoo amount first with IBKR fallback (the
    view's documented naive default; 606 of 42,926 two-source events disagree beyond rounding,
    bounded except part-stock specials). Outside `dividend_event_coverage` the window is
    unknown, never zero: the builder supplies NaN for out-of-coverage dates and a window
    holding one is NaN (no_fill). 0.0 over a fully covered window is measured (zero_is_state).

Registry: all ten enter `concept_registry` as `candidate` (domain `feature`), V2_ONLY_COLUMNS
with the 553 pattern, `feature_vectors_v2` real columns by migration, promotion only when a
family prereg names the column. The three never-computed `rank_z` concept rows retire to
`deprecated` through ConceptRegistryService in the same landing (todo 421's registry half).

Grid-kernel memory (daily bars): residual family = factor_beta.window + max(z_window,
idio_volatility.window, lag1_acf_window, beta_stability.window) + 2; max_daily_return = its
window; max_drawdown/downside_deviation = their windows; dividend_yield = window + 1;
size_proxy (row grid) = its window. Pass-throughs declare 0, the macro pattern.
