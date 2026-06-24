# IC Discovery Report — Phase 139 Ensemble Alpha

**Generated:** 2026-06-24T06:40:13.104959+00:00
**Weight version:** `v1`
**Mode:** Shadow (no live execution)

## Overall Summary

| Metric | Value |
| ------ | ----- |
| Total strata with weights | 28 |
| Total bars scored | 3,523,626 |
| Total alpha events emitted | 2,845,878 |
| Overall emission rate | 80.77% |
| Mean effective N | 11.5 |
| Median effective N | 11.1 |
| Long events | 2,721,781 (95.6%) |
| Short events | 124,097 (4.4%) |

## Strata Summary

| Symbol | TF | Regime | Features | Effective N |
| ------ | -- | ------ | -------- | ----------- |
| QQQ | 15m | ranging | 23 | 14.7 |
| QQQ | 15m | trending_down | 16 | 11.4 |
| QQQ | 15m | trending_up | 23 | 17.8 |
| QQQ | 1h | trending_down | 17 | 10.1 |
| QQQ | 5m | trending_down | 20 | 15.0 |
| QQQ | 5m | trending_up | 15 | 12.8 |
| SPY | 15m | ranging | 18 | 14.3 |
| SPY | 15m | trending_down | 11 | 7.9 |
| SPY | 15m | trending_up | 10 | 9.0 |
| SPY | 1h | ranging | 17 | 9.3 |
| SPY | 1h | trending_down | 11 | 8.4 |
| SPY | 5m | ranging | 19 | 15.0 |
| SPY | 5m | trending_down | 14 | 9.8 |
| SPY | 5m | trending_up | 11 | 7.9 |
| TLT | 15m | ranging | 18 | 11.4 |
| TLT | 15m | trending_down | 16 | 12.9 |
| TLT | 15m | trending_up | 17 | 10.2 |
| TLT | 1h | trending_up | 20 | 16.6 |
| TLT | 5m | ranging | 19 | 12.1 |
| TLT | 5m | trending_down | 11 | 7.1 |
| TLT | 5m | trending_up | 16 | 9.5 |
| XLF | 15m | ranging | 18 | 13.9 |
| XLF | 15m | trending_down | 14 | 10.5 |
| XLF | 15m | trending_up | 20 | 15.1 |
| XLF | 1h | ranging | 8 | 5.5 |
| XLF | 1h | trending_down | 21 | 14.4 |
| XLF | 5m | ranging | 15 | 10.9 |
| XLF | 5m | trending_up | 12 | 7.2 |

## Emission Rates by Symbol × Timeframe

| Symbol | TF | Bars Scored | Events | Emission Rate | Long | Short |
| ------ | -- | ----------- | ------ | ------------- | ---- | ----- |
| QQQ | 15m | 350,144 | 176,592 | 50.43% | 150,878 | 25,714 |
| QQQ | 1h | 63,976 | 46,014 | 71.92% | 42,925 | 3,089 |
| QQQ | 5m | 431,523 | 429,420 | 99.51% | 429,411 | 9 |
| SPY | 15m | 350,386 | 287,289 | 81.99% | 271,682 | 15,607 |
| SPY | 1h | 105,621 | 91,969 | 87.08% | 91,962 | 7 |
| SPY | 5m | 469,601 | 418,971 | 89.22% | 388,747 | 30,224 |
| TLT | 15m | 350,128 | 181,000 | 51.70% | 159,327 | 21,673 |
| TLT | 1h | 46,375 | 45,157 | 97.37% | 43,249 | 1,908 |
| TLT | 5m | 469,403 | 407,854 | 86.89% | 407,666 | 188 |
| XLF | 15m | 350,168 | 303,895 | 86.78% | 287,681 | 16,214 |
| XLF | 1h | 103,472 | 58,734 | 56.76% | 49,270 | 9,464 |
| XLF | 5m | 432,829 | 398,983 | 92.18% | 398,983 | 0 |

## Top Features by Stratum (Sample)

### QQQ / 15m / ranging
Effective N = 14.7 | Features = 23

| Feature | Weight | IC Sharpe |
| ------- | ------ | --------- |
| bar_close_pos | 0.0946 | 0.398 |
| ofi_z | 0.0865 | 0.364 |
| gap_z | 0.0836 | 0.351 |
| volume_z | 0.0799 | 0.336 |
| cvd_slope_z | 0.0771 | 0.324 |

### QQQ / 15m / trending_down
Effective N = 11.4 | Features = 16

| Feature | Weight | IC Sharpe |
| ------- | ------ | --------- |
| dow_sin | 0.1586 | 0.594 |
| atr_z | 0.1198 | 0.448 |
| garch_ratio | 0.0982 | 0.367 |
| gap_z | 0.0823 | 0.308 |
| adx | 0.0805 | 0.301 |

### QQQ / 15m / trending_up
Effective N = 17.8 | Features = 23

| Feature | Weight | IC Sharpe |
| ------- | ------ | --------- |
| cci_mid | 0.0926 | 0.664 |
| adx | 0.0726 | 0.520 |
| rsi_fast | 0.0710 | 0.509 |
| cci_slow | 0.0646 | 0.463 |
| high_52w_dist | 0.0641 | 0.459 |

### QQQ / 1h / trending_down
Effective N = 10.1 | Features = 17

| Feature | Weight | IC Sharpe |
| ------- | ------ | --------- |
| momentum_z_fast | 0.1458 | 0.470 |
| in_overlap | 0.1450 | 0.467 |
| range_position | 0.1212 | 0.391 |
| momentum_z_mid | 0.1145 | 0.369 |
| dow_sin | 0.1005 | 0.324 |

### QQQ / 5m / trending_down
Effective N = 15.0 | Features = 20

| Feature | Weight | IC Sharpe |
| ------- | ------ | --------- |
| gap_z | 0.0898 | 0.183 |
| in_overlap | 0.0813 | 0.166 |
| momentum_z_mid | 0.0802 | 0.163 |
| momentum_reversal_z | 0.0791 | 0.161 |
| rsi_fast | 0.0791 | 0.161 |

### QQQ / 5m / trending_up
Effective N = 12.8 | Features = 15

| Feature | Weight | IC Sharpe |
| ------- | ------ | --------- |
| momentum_z_slow | 0.1180 | 0.460 |
| above_wk_vwap | 0.1071 | 0.418 |
| aroon_fast | 0.0962 | 0.375 |
| rsi_mid | 0.0932 | 0.363 |
| rel_volume | 0.0929 | 0.362 |

### SPY / 15m / ranging
Effective N = 14.3 | Features = 18

| Feature | Weight | IC Sharpe |
| ------- | ------ | --------- |
| dow_sin | 0.1221 | 0.361 |
| in_overlap | 0.1030 | 0.305 |
| adx | 0.0957 | 0.283 |
| shannon | 0.0848 | 0.251 |
| atr_z | 0.0706 | 0.209 |

### SPY / 15m / trending_down
Effective N = 7.9 | Features = 11

| Feature | Weight | IC Sharpe |
| ------- | ------ | --------- |
| cvd_slope_z | 0.1960 | 0.414 |
| days_to_month_end | 0.1543 | 0.326 |
| momentum_reversal_z | 0.1454 | 0.307 |
| informed_flow | 0.1245 | 0.263 |
| bar_close_pos | 0.0901 | 0.190 |

*... 20 more strata omitted for brevity ...*
## Effective N Distribution

Mean: 11.5  Median: 11.1

Effective N represents the number of independently-informative features
after Ledoit-Wolf shrinkage and cluster deflation. Values >= 3.0 are required
before alpha events are emitted (the `alpha.ensemble.effective_n_gate` APR key).

## Notes

- This report covers the **4-symbol validation corpus** (SPY/TLT/XLF/QQQ × 4 TFs).
  Full 58-ETF corpus run is pending (Phase 138 P8 full backfill).
- All events are in **shadow mode** — no live execution or position sizing.
- Weights are version `v1` derived via Ledoit-Wolf shrinkage + cluster deflation.
- Direction-aware CI gate applied: long events require alpha_ci_lower > 0;
  short events require alpha_ci_upper < 0.