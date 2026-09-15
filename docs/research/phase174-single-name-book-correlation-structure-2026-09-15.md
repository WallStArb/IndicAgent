# Single-name book cross-sectional correlation structure (2026-09-15)

**Author:** Claude Sonnet 5, mid-execution of Phase 174 Wave 2/3, in response to a design
question raised by Brandon about restricting the down-cap sample to 1d bars.

**Purpose:** empirically check whether the existing 128-name single-name equity book's
diversification structure supports the assumption that adding more raw symbols increases
effective breadth proportionally, before committing to a large-scale down-cap backfill.
Informs D-09/D-10 in `174-CONTEXT.md`.

## Method

- Population: `instrument_tags` symbols tagged `single_name_equity` (128 total; 117 retained
  after dropping 11 with <95% daily-bar coverage since 2018: BNTX, COIN, CRWD, CTVA, DOCS, DOW,
  GEV, LIN, ODFL, RVMD, UBER).
- Data: daily close prices, `market_data_ohlcv_tradeable` (`timeframe='1d'`), 2018-01-01 to
  2026-09-02 (2,175 trading days).
- Returns: `ln(close[t] / close[t-1])`, close-to-close (descriptive correlation-structure
  characterization, not an IC/alpha measurement — the executable-return invariant governing
  `forward_returns`/`ic_engine` does not apply here).
- Regime conditioning: `market_regimes` where `regime_group='equity'` and `tf='1d'`, joined on
  date.
- Effective breadth: standard diversification-shrinkage formula,
  `n_eff = N / (1 + (N-1)·avg_pairwise_corr)`.

## Results

| Regime | N | Avg pairwise corr | Median | PC1 variance share | PC1-3 variance share | n_eff |
|---|---|---|---|---|---|---|
| All regimes (unconditional) | 117 | 0.3164 | 0.3050 | 33.50% | 45.32% | 3.10 |
| low_bull | 117 | 0.1731 | 0.1624 | 20.09% | 35.05% | 5.55 |
| mid_bull | 117 | 0.1423 | 0.1244 | 17.43% | 32.94% | 6.68 |
| high_bull | 117 | 0.3020 | 0.3097 | 33.24% | 47.92% | 3.25 |
| high_neutral | 117 | 0.2030 | 0.1977 | 22.62% | 37.08% | 4.77 |
| **high_bear** | 117 | **0.4789** | 0.4832 | **49.49%** | 61.01% | **2.07** |
| mid_bear | 117 | 0.3213 | 0.3103 | 34.78% | 46.92% | 3.06 |
| mid_neutral | 117 | 0.2061 | 0.1926 | 22.96% | 36.07% | 4.70 |
| low_neutral | 117 | 0.1985 | 0.1894 | 22.20% | 34.71% | 4.87 |
| low_bear | 117 | 0.3111 | 0.3060 | 33.53% | 46.82% | 3.15 |

## Interpretation

1. The existing single-name book delivers roughly 3 independent bets out of 117 raw symbols
   (n_eff), consistent with and explaining this project's separately-measured 8.4-effective-
   breadth-vs-230-raw-feature-count gap.
2. `high_bear` — the exact regime that OOM'd `ic_engine` at 182 symbols (todo 371) — is the
   worst case for diversification: PC1 (the market factor) explains ~49% of variance and n_eff
   drops to ~2.1. This is structural, not incidental: common-factor dominance is highest exactly
   when idiosyncratic signal is needed most.
3. Because `n_eff → 1/avg_corr` as N grows, no amount of additional large/mega-cap-correlated
   symbols meaningfully raises effective breadth past ~3.2. A generic scale-out (more large-cap
   names, any timeframe) would be close to worthless by this math — it validates that the
   down-cap-specific hypothesis (D-02) is the right lever, not simply "more raw symbols."
4. This diagnostic cannot directly test the down-cap hypothesis (no down-cap price history
   exists yet) — it only characterizes the existing large/mega-cap-heavy book. D-10's
   pre-registered pilot gate exists to test the actual down-cap population's correlation
   structure before committing to a full-scale backfill.

## Reproduction

Query: `instrument_tags` filtered to `tag='single_name_equity'`, joined to
`market_data_ohlcv_tradeable` (`timeframe='1d'`) and `market_regimes`
(`regime_group='equity'`, `tf='1d'`). Analysis script (ad hoc, not committed to `scripts/` —
D-10's implementation should produce a reusable, committed version):
`np.linalg.eigvalsh` on the filled correlation matrix for PC-variance-share; pairwise
correlation summary via `pandas.DataFrame.corr(min_periods=20)`.
