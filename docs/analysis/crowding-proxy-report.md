# Crowding Proxy Report

Todo 072 (L7-3): regresses per-stratum, per-epoch `alpha_score` on three public-factor
proxies computed independently from daily bars (12-1 momentum, 5-day reversal, 21-day
realized vol as a low-vol-tilt proxy). Diagnostic only -- no gate, no promotion
decision. High R^2 prices decay risk (crowded alpha); it does not invalidate the edge.

Factors joined no-lookahead: strictly the last daily close before each observation's
date. Min-obs gate: 30 symbol-days per stratum.

## Strata with a fitted regression

| tf | regime | epoch | n | R² | coef(mom12-1) | coef(rev5d) | coef(lowvol) |
|---|---|---|---|---|---|---|---|
| 1d | mid_bull | run_2025122405150000 | 9342 | 0.2674 | 0.2943 (p=0.000) | 0.1850 (p=0.001) | 9.6537 (p=0.000) |
| 15m | high_bull | run_2025122405150000 | 689 | 0.0880 | 0.0900 (p=0.787) | 7.3431 (p=0.000) | 44.4645 (p=0.000) |
| 15m | high_bear | run_2025122405150000 | 45422 | 0.0677 | 0.0182 (p=0.582) | 6.9600 (p=0.000) | 9.0625 (p=0.000) |
| 15m | mid_neutral | run_2025122405150000 | 20977 | 0.0359 | 0.0035 (p=0.970) | 14.0484 (p=0.000) | 13.7962 (p=0.000) |
| 15m | low_bull | run_2025122405150000 | 108765 | 0.0263 | 0.1951 (p=0.000) | 9.6991 (p=0.000) | 8.2650 (p=0.000) |
| 5m | high_bull | run_2025122405150000 | 39608 | 0.0258 | 0.5655 (p=0.000) | 2.9294 (p=0.000) | 22.4300 (p=0.000) |
| 15m | low_bear | run_2025122405150000 | 633 | 0.0236 | 0.0372 (p=0.609) | -1.6051 (p=0.001) | -2.5090 (p=0.318) |
| 5m | mid_neutral | run_2025122405150000 | 22042 | 0.0196 | -0.4903 (p=0.000) | 10.7099 (p=0.000) | 43.4645 (p=0.000) |
| 15m | mid_bear | run_2025122405150000 | 490 | 0.0166 | 0.3936 (p=0.286) | -1.3715 (p=0.474) | 22.1258 (p=0.007) |
| 5m | high_neutral | run_2025122405150000 | 632 | 0.0132 | -0.1044 (p=0.235) | 0.6889 (p=0.190) | -4.8082 (p=0.013) |
| 5m | high_bear | run_2025122405150000 | 44625 | 0.0129 | -0.0236 (p=0.152) | 1.2740 (p=0.000) | 2.9164 (p=0.000) |
| 5m | low_bear | run_2025122405150000 | 1255 | 0.0114 | -0.0309 (p=0.357) | -0.3366 (p=0.139) | -3.1464 (p=0.001) |
| 5m | mid_bear | run_2025122405150000 | 20113 | 0.0072 | -0.1258 (p=0.001) | 0.5892 (p=0.003) | -8.6236 (p=0.000) |
| 5m | low_neutral | run_2025122405150000 | 11295 | 0.0058 | -0.3510 (p=0.041) | -3.2482 (p=0.004) | 30.1514 (p=0.000) |
| 5m | mid_bull | run_2025122405150000 | 2741 | 0.0042 | 0.0436 (p=0.098) | -0.6185 (p=0.009) | 0.2333 (p=0.766) |
| 15m | mid_bull | run_2025122405150000 | 1466 | 0.0029 | -0.0954 (p=0.105) | 0.4249 (p=0.305) | 0.0035 (p=0.998) |

## Strata skipped (insufficient N)

| tf | regime | epoch | n |
|---|---|---|---|
| 15m | high_neutral | run_2025122405150000 | 2 |
| 5m | low_bull | run_2025122405150000 | 4 |

## Verdict

Highest stratum R² observed: **0.2674** -- no stratum shows heavy public-factor overlap yet.
