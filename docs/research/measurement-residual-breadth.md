# Measurement: residual breadth of the compute_eligible universe

**Author:** Claude (Opus 5.5), 2026-09-25. Step 0 of
`docs/plans/2026-09-25-alpha-research-architecture.md` (section 5).
**Script:** `scripts/analysis/residual_breadth_diagnostic.py` (read-only; window capped at
`alpha.validation.oos_start`). Raw output: `logs/residual_breadth/*.json` (not in git).

## Result

After removing market and sector moves, the 233-name universe carries 51 to 66 independent
bets per daily cross-section and 63 to 83 per hourly one, stable across three periods. The
13-symbol sleeve carries 6.3 raw and 8.4 residualized. The breadth premise of the
architecture holds, so section 4's families run on this panel as planned.

| Window | tf | Names | Raw | Market residual | Market + sector residual | Noise ceiling |
|---|---|---|---|---|---|---|
| 2019-2025 | 1d | 227 | 5.5 | 29.6 | **51.0** | 201 |
| 2019-2025 | 1h | 213 | 6.8 | 37.5 | **63.1** | 209 |
| 2019-2025 | 15m | 211 | 7.8 | 42.0 | **71.8** | 210 |
| 2013-2018 | 1d | 196 | 6.6 | 36.6 | **63.8** | 174 |
| 2013-2018 | 1h | 194 | 8.6 | 51.4 | **82.6** | 190 |
| 2007-2012 | 1d | 161 | 3.8 | 38.8 | **65.5** | 145 |
| 2007-2012 | 1h | 131 | 5.0 | 53.5 | **79.9** | 129 |
| 2019-2025, sleeve only | 1d | 13 | 6.3 | 8.1 | 8.4 | 13 |

The effective number of bets is the participation ratio of the correlation matrix's
eigenvalues, (sum of eigenvalues)^2 / (sum of squared eigenvalues). The sleeve's raw 6.3
reproduces the value recorded for Phase 174's Gate A, which checks the method end to end.

## Method

- Returns come from `market_data_ohlcv_tradeable`. Intraday returns stay within one session:
  the first bar of a session is its own open to close, so overnight gaps never enter.
- Names need at least 80% coverage in the window. Correlations are pairwise-complete, with a
  minimum overlap of 100 observations.
- The market residual regresses each name on the equal-weighted universe return. The sector
  residual adds the leave-one-out equal-weighted return of the name's
  `contract_details->>'sector'` group, for groups of three or more names. Loadings are
  full-sample, because this measures structure and is not a causal input to a test.
- The noise ceiling permutes each column in time independently. It shows the most breadth
  the sample size allows for this many names.

## Reading it

- **The market factor is almost everything in raw returns.** One eigenvalue carries 34-41% of
  the variance and raw breadth is 4-9, which matches the Phase 174 decorrelation failure.
  Residualizing is the step that unlocks breadth. This is why S1's residual target is
  mandatory, not optional.
- **Residual factors remain.** The market and sector residual (51-83) sits well below the noise
  ceiling (129-210). Removing the top 10 principal components instead gives 95-120, so
  styles, rates and commodity exposure still carry shared variance. A richer S1 factor set
  would raise usable breadth further.
- **Intraday gains are partly an artifact.** The step from 1d to 15m (51 to 72) is consistent
  with the Epps effect: nonsynchronous trading depresses short-interval correlations (raw
  average pairwise correlation falls from 0.36 to 0.29). Treat the 1d figure as the
  conservative cross-sectional breadth. What intraday really adds is periods per year.
- **What this buys, as an upper bound.** By the fundamental law, a residual IC of 0.01 per
  period gives an IR of about 0.01 x sqrt(bets per year). The sleeve at 1d has about 1,600
  bets a year, for an IR of about 0.4. The residual panel at 1d has about 12,900 (IR about
  1.1), and at 1h about 111,000 (IR about 3.3). These figures assume independent periods,
  a one-bar holding period and realized IC, before costs. Overlapping horizons and signal
  decay cut them, and costs bite hardest at 1h. Still, even the conservative 1d panel changes
  the resolution time in evidence framework section 2 from decades to years.

## Implications for the plan

- Families run on the residualized 233-name panel, as the architecture assumed. There is no
  case for reverting to the sleeve.
- Run 1d variants beside intraday ones where the family allows it. Daily bars have less Epps
  distortion, less bid-ask bounce and lower cost, and they already carry about 8 times the
  sleeve's cross-sectional breadth.
- Consider extending S1's factor set beyond market and sector (principal components or
  style factors, estimated causally), since the principal-component tail shows usable breadth
  it would unlock.
