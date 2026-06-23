# IC Discovery Report — Phase 138

**Generated:** 2026-06-23T22:18:52.634365+00:00  
**Training window end:** 2026-06-23 16:00:00+00  
**Symbols:** SPY, TLT, XLF, QQQ  

## 1. Summary

| Metric | Value |
|--------|-------|
| Total cells computed | 12,444 |
| Cells passing BH-FDR | 249 |
| Cells passing walk-forward | 1,022 |
| Cells with non-null IC Sharpe | 8,904 |
| Passing features (passes_walkforward=true, is_pooled=false) | 683 |

## 2. Top 20 Features by IC Sharpe (passes_walkforward=true, is_pooled=false)

| Feature | Symbol | TF | Regime | Lookahead | IC | CI Lower | IC Sharpe | passes_fdr |
|---------|--------|----|---------|-----------|----|----------|-----------|------------|
| in_overlap | QQQ | 1h | trending_up | 1 | 0.2383 | 0.1122 | 1.014 | Y |
| opening_range | XLF | 1h | trending_up | 1 | 0.3196 | 0.1592 | 0.986 | Y |
| atr_z | QQQ | 5m | ranging | 5 | 0.1577 | 0.0970 | 0.948 | Y |
| ret_skew_z | XLF | 1h | trending_up | 60 | 0.0755 | -0.0056 | 0.927 | N |
| ret_skew_z | QQQ | 5m | ranging | 60 | 0.1060 | 0.0459 | 0.881 | N |
| quarter_position | TLT | 15m | trending_up | 5 | 0.1081 | 0.0549 | 0.870 | Y |
| dow_cos | TLT | 5m | ranging | 5 | 0.1127 | 0.0595 | 0.816 | N |
| informed_flow | XLF | 5m | trending_down | 1 | 0.1630 | 0.0651 | 0.814 | Y |
| momentum_reversal_z | TLT | 1h | trending_up | 60 | 0.0962 | 0.0312 | 0.810 | N |
| in_overlap | XLF | 1h | trending_up | 1 | 0.2545 | 0.0800 | 0.801 | Y |
| vol_ratio | QQQ | 5m | ranging | 60 | 0.1201 | 0.0465 | 0.789 | Y |
| momentum_z_mid | TLT | 1h | trending_up | 60 | 0.0988 | 0.0328 | 0.781 | N |
| momentum_z_fast | TLT | 1h | trending_up | 60 | 0.1081 | 0.0381 | 0.775 | N |
| atr_z | QQQ | 5m | ranging | 60 | 0.1644 | 0.1003 | 0.769 | Y |
| in_ny_session | QQQ | 5m | ranging | 20 | 0.1466 | 0.0797 | 0.753 | Y |
| hmm_duration | TLT | 5m | trending_down | 60 | 0.0966 | 0.0533 | 0.743 | N |
| in_ny_session | QQQ | 5m | ranging | 60 | 0.1433 | 0.0636 | 0.740 | Y |
| vol_ratio | QQQ | 5m | ranging | 1 | 0.1101 | 0.0406 | 0.726 | N |
| hmm_duration | TLT | 5m | trending_down | 20 | 0.1161 | 0.0617 | 0.725 | N |
| momentum_z_slow | XLF | 1h | trending_up | 60 | 0.0949 | 0.0135 | 0.721 | N |

## 3. All Regime-Stratified Rows with passes_walkforward=true

*N=683 rows. Sorted by IC Sharpe descending.*

| Feature | Symbol | TF | Regime | Lookahead | IC | CI Lower | IC Sharpe | passes_fdr | N indep |
|---------|--------|----|---------|-----------|----|----------|-----------|------------|---------|
| quarter_position | TLT | 15m | trending_up | 5 | 0.1081 | 0.0549 | 0.870 | Y | 894 |
| dow_cos | TLT | 5m | ranging | 5 | 0.1127 | 0.0595 | 0.816 | N | 877 |
| momentum_reversal_z | TLT | 1h | trending_up | 60 | 0.0962 | 0.0312 | 0.810 | N | 773 |
| momentum_z_mid | TLT | 1h | trending_up | 60 | 0.0988 | 0.0328 | 0.781 | N | 773 |
| momentum_z_fast | TLT | 1h | trending_up | 60 | 0.1081 | 0.0381 | 0.775 | N | 773 |
| hmm_duration | TLT | 5m | trending_down | 60 | 0.0966 | 0.0533 | 0.743 | N | 918 |
| hmm_duration | TLT | 5m | trending_down | 20 | 0.1161 | 0.0617 | 0.725 | N | 918 |
| rsi_slow | TLT | 1h | trending_up | 1 | 0.0680 | -0.0075 | 0.683 | N | 773 |
| cci_mid | QQQ | 15m | trending_up | 60 | 0.0860 | 0.0315 | 0.664 | N | 1052 |
| cci_fast | TLT | 1h | trending_up | 60 | 0.0942 | 0.0295 | 0.660 | N | 773 |
| range_position | TLT | 1h | trending_up | 1 | 0.1388 | 0.0565 | 0.654 | Y | 773 |
| dow_sin | SPY | 1h | ranging | 60 | 0.0908 | 0.0159 | 0.653 | N | 668 |
| vol_ratio | XLF | 15m | trending_down | 1 | 0.1605 | 0.0699 | 0.653 | Y | 803 |
| cci_mid | QQQ | 15m | trending_up | 20 | 0.0857 | 0.0237 | 0.622 | N | 1052 |
| in_ny_session | XLF | 15m | trending_down | 1 | 0.1668 | 0.0658 | 0.620 | Y | 803 |
| rel_volume | XLF | 15m | trending_down | 1 | 0.1745 | 0.0698 | 0.612 | Y | 803 |
| ret_acf1_z | TLT | 15m | trending_down | 5 | 0.0774 | 0.0171 | 0.607 | N | 957 |
| dow_sin | QQQ | 15m | trending_down | 60 | 0.1110 | 0.0819 | 0.593 | Y | 3969 |
| gap_z | TLT | 1h | trending_up | 60 | 0.0666 | -0.0009 | 0.537 | N | 773 |
| in_ny_session | XLF | 15m | trending_up | 5 | 0.0714 | 0.0396 | 0.537 | N | 1063 |
| quarter_position | TLT | 5m | ranging | 1 | 0.0919 | 0.0472 | 0.534 | N | 877 |
| garch_ratio | SPY | 1h | ranging | 5 | 0.1007 | 0.0305 | 0.533 | N | 668 |
| days_to_month_end | SPY | 15m | trending_up | 20 | 0.0876 | 0.0278 | 0.532 | N | 896 |
| in_ny_session | TLT | 15m | trending_down | 20 | 0.0631 | 0.0272 | 0.523 | N | 957 |
| adx | QQQ | 15m | trending_up | 60 | 0.0551 | 0.0014 | 0.521 | N | 1052 |
| quarter_position | TLT | 15m | trending_up | 20 | 0.0809 | 0.0284 | 0.521 | N | 894 |
| dow_sin | TLT | 5m | ranging | 20 | 0.0977 | 0.0315 | 0.516 | N | 877 |
| rel_volume | XLF | 15m | trending_up | 5 | 0.0733 | 0.0233 | 0.516 | N | 1063 |
| rsi_fast | QQQ | 15m | trending_up | 20 | 0.0803 | 0.0177 | 0.509 | N | 1052 |
| aroon_fast | XLF | 1h | trending_down | 60 | 0.0775 | 0.0278 | 0.505 | N | 1046 |
| rel_volume | SPY | 5m | trending_down | 1 | 0.0737 | 0.0223 | 0.502 | N | 1039 |
| volume_z | XLF | 15m | trending_down | 1 | 0.1344 | 0.0331 | 0.501 | Y | 803 |
| momentum_reversal_z | SPY | 1h | trending_down | 60 | 0.0591 | 0.0039 | 0.498 | N | 1093 |
| hma_slope_z | SPY | 15m | trending_up | 60 | 0.0714 | 0.0156 | 0.481 | N | 895 |
| momentum_z_slow | TLT | 15m | trending_down | 60 | 0.0683 | 0.0102 | 0.478 | N | 957 |
| dow_sin | SPY | 1h | ranging | 1 | 0.0590 | -0.0091 | 0.476 | N | 668 |
| aroon_fast | SPY | 5m | trending_up | 60 | 0.0756 | 0.0087 | 0.474 | N | 761 |
| hma_slope_z | XLF | 1h | trending_down | 60 | 0.0870 | 0.0333 | 0.473 | N | 1046 |
| momentum_z_fast | QQQ | 1h | trending_down | 60 | 0.0677 | 0.0099 | 0.470 | N | 1066 |
| days_to_month_end | SPY | 1h | ranging | 60 | 0.0837 | 0.0091 | 0.469 | N | 668 |
| in_overlap | QQQ | 1h | trending_down | 5 | 0.1086 | 0.0252 | 0.467 | Y | 1067 |
| cci_slow | QQQ | 15m | trending_up | 60 | 0.0734 | 0.0159 | 0.463 | N | 1052 |
| momentum_z_slow | QQQ | 5m | trending_up | 60 | 0.0740 | 0.0224 | 0.460 | N | 1173 |
| aroon_fast | SPY | 5m | trending_down | 1 | 0.0666 | 0.0066 | 0.460 | N | 1039 |
| high_52w_dist | QQQ | 15m | trending_up | 20 | 0.0779 | 0.0176 | 0.459 | N | 1052 |
| momentum_z_fast | QQQ | 15m | trending_up | 5 | 0.0707 | 0.0089 | 0.453 | N | 1052 |
| days_to_month_end | SPY | 15m | trending_up | 60 | 0.0671 | 0.0128 | 0.451 | N | 895 |
| cvd_slope_z | SPY | 15m | trending_up | 1 | 0.0647 | 0.0009 | 0.450 | N | 896 |
| atr_z | QQQ | 15m | trending_down | 60 | 0.0815 | 0.0487 | 0.448 | Y | 3969 |
| bar_close_pos | TLT | 15m | trending_down | 60 | 0.0572 | 0.0038 | 0.448 | N | 957 |
| momentum_reversal_z | SPY | 1h | ranging | 60 | 0.0813 | 0.0174 | 0.440 | N | 668 |
| month_position | TLT | 5m | ranging | 1 | 0.0606 | 0.0141 | 0.439 | N | 877 |
| opening_range | TLT | 1h | trending_up | 1 | 0.1047 | -0.0323 | 0.437 | N | 773 |
| informed_flow | XLF | 1h | trending_down | 60 | 0.0616 | 0.0058 | 0.437 | N | 1046 |
| momentum_z_mid | XLF | 1h | trending_down | 60 | 0.0816 | 0.0230 | 0.436 | N | 1046 |
| aroon_fast | SPY | 5m | trending_down | 5 | 0.0521 | -0.0042 | 0.434 | N | 1039 |
| bar_close_pos | QQQ | 15m | trending_up | 60 | 0.0927 | 0.0274 | 0.431 | N | 1052 |
| aroon_fast | XLF | 1h | ranging | 60 | 0.0485 | -0.0170 | 0.430 | N | 678 |

## 4. Diagnostic: Pooled vs Regime-Stratified

Pooled rows (is_pooled=true) are DIAGNOSTIC ARTIFACTS ONLY. Phase 139 ensemble reads exclusively WHERE is_pooled=false.

| TF | Type | Total | Passing FDR | Passing WF | Avg IC Sharpe | Max IC Sharpe |
|----|------|-------|-------------|------------|---------------|---------------|
| 15m | regime | 2928 | 52 | 322 | 0.007 | 0.870 |
| 15m | pooled | 976 | 22 | 103 | -0.026 | 0.414 |
| 1d | pooled | 732 | 0 | 0 | NULL | NULL |
| 1h | regime | 2928 | 13 | 130 | -0.011 | 1.014 |
| 1h | pooled | 976 | 15 | 115 | -0.004 | 0.632 |
| 5m | regime | 2928 | 104 | 231 | 0.003 | 0.948 |
| 5m | pooled | 976 | 43 | 121 | -0.011 | 0.270 |

## 5. Cells Below IC Sharpe Gate (n_raw_bars < 20,000)

These (symbol, tf, regime) cells had fewer than 20,000 raw bars (n_independent x stride < 20,000), so ic_sharpe was not computed. IC values and FDR results are still computed; only rolling-window Sharpe is absent.

| Symbol | TF | Regime | Max N (subsampled) |
|--------|----|--------|-------------------|
| QQQ | 15m | ranging | 815 |
| QQQ | 15m | trending_down | 3970 |
| QQQ | 15m | trending_up | 1052 |
| QQQ | 1h | ranging | 622 |
| QQQ | 1h | trending_down | 1067 |
| QQQ | 1h | trending_up | 497 |
| QQQ | 5m | ranging | 628 |
| QQQ | 5m | trending_down | 6020 |
| QQQ | 5m | trending_up | 1173 |
| SPY | 15m | ranging | 3981 |
| SPY | 15m | trending_down | 965 |
| SPY | 15m | trending_up | 896 |
| SPY | 1h | ranging | 668 |
| SPY | 1h | trending_down | 1094 |
| SPY | 1h | trending_up | 427 |
| SPY | 5m | ranging | 6028 |
| SPY | 5m | trending_down | 1039 |
| SPY | 5m | trending_up | 761 |
| TLT | 15m | ranging | 3986 |
| TLT | 15m | trending_down | 957 |
| TLT | 15m | trending_up | 894 |
| TLT | 1h | ranging | 433 |
| TLT | 1h | trending_down | 308 |
| TLT | 1h | trending_up | 773 |
| TLT | 5m | ranging | 877 |
| TLT | 5m | trending_down | 918 |
| TLT | 5m | trending_up | 6030 |
| XLF | 15m | ranging | 3971 |
| XLF | 15m | trending_down | 803 |
| XLF | 15m | trending_up | 1063 |
| XLF | 1h | ranging | 678 |
| XLF | 1h | trending_down | 1047 |
| XLF | 1h | trending_up | 461 |
| XLF | 5m | ranging | 6031 |
| XLF | 5m | trending_down | 612 |
| XLF | 5m | trending_up | 1184 |

