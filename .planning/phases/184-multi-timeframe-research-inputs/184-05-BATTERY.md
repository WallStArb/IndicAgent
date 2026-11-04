# 184-05 persistent-predictor E17 battery report (D7 guard 6, B6)

Driver: `.venv/bin/python scripts/research/e17_null_battery.py 184-05-battery.json --battery src.intelligence.research.null_battery_persistent --sims 1000 --workers 6`

Battery module commit: 49e21bb41 (clean certified code, no uncommitted change; the simulation code is unchanged in later commits, which only fill `PASSING_CERTIFICATES` and the refusal message). Record: 26 scenarios, 1,000 simulations each, 4,000-session panels, 60 names. The raw record is not committed (cells and counts are in the table).

## Rule, fixed before the run

A gating cell holds size when the rejection count of both arms (`member`, the family-level E17 test with the daily overlap statistic on a daily book; `book_equal`, the S8 book test through `book.book_timing`) is at most the upper 99% binomial bound at 0.05 (67) and at 0.01 (18), `scipy.stats.binom.ppf(0.99, 1000, alpha)`. 1,000 simulations cannot resolve 0.00167 (bound 5, one-sided noise dominates), so that column is descriptive and never gates (184-REVIEWS row 5). Rates are shown with the Monte Carlo se, sqrt(p(1-p)/1000). A certificate passes only when every gating cell carrying it passes. Diagnostic cells (`hostile_tau200`) are listed and never gate.

## Cells

| cell | role | identity | window | smoothing_half_life | source_tf | book_tf | horizon | combiner | max_age_rows | max_gap_rows | source_memory_bars_max | tau (sessions) | L (sessions) | mean tested sessions | member 0.05 (se) | member 0.01 (se) | member 0.00167 (se, descriptive) | book 0.05 (se) | book 0.01 (se) | book 0.00167 (se, descriptive) | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| f1d_tau1 | gate | feature | None | None | 1d | 1d | 1 | equal_weight | 1 | None | 252 | 1 | 254 | 3434 | 0.044 (0.007) | 0.008 (0.003) | 0.002 (0.001) | 0.044 (0.007) | 0.008 (0.003) | 0.002 (0.001) | PASS |
| f1d_tau5 | gate | feature | None | None | 1d | 1d | 1 | equal_weight | 1 | None | 252 | 5 | 254 | 3434 | 0.047 (0.007) | 0.004 (0.003) | 0.002 (0.001) | 0.047 (0.007) | 0.005 (0.003) | 0.002 (0.001) | PASS |
| f1d_tau20 | gate | feature | None | None | 1d | 1d | 1 | equal_weight | 1 | None | 252 | 20 | 254 | 3434 | 0.044 (0.007) | 0.011 (0.003) | 0.000 (0.001) | 0.046 (0.007) | 0.011 (0.003) | 0.001 (0.001) | PASS |
| f1d_tau60 | gate | feature | None | None | 1d | 1d | 1 | equal_weight | 1 | None | 252 | 60 | 254 | 3434 | 0.051 (0.007) | 0.012 (0.003) | 0.002 (0.001) | 0.069 (0.007) | 0.015 (0.003) | 0.003 (0.001) | FAIL |
| f1d_tau200 | gate | feature | None | None | 1d | 1d | 1 | equal_weight | 1 | None | 252 | 200 | 254 | 3434 | 0.055 (0.007) | 0.011 (0.003) | 0.001 (0.001) | 0.075 (0.007) | 0.024 (0.003) | 0.007 (0.001) | FAIL |
| f1d_static_tau200 | gate | feature | None | None | 1d | 1d | 1 | equal_weight | 1 | None | 252 | 200 | 254 | 3434 | 0.046 (0.007) | 0.005 (0.003) | 0.001 (0.001) | 0.074 (0.007) | 0.015 (0.003) | 0.003 (0.001) | FAIL |
| f1h_tau20 | gate | feature | None | None | 1h | 1d | 1 | equal_weight | 1 | None | 140 | 20 | 22 | 3496 | 0.045 (0.007) | 0.011 (0.003) | 0.003 (0.001) | 0.047 (0.007) | 0.011 (0.003) | 0.003 (0.001) | PASS |
| f1h_tau200 | gate | feature | None | None | 1h | 1d | 1 | equal_weight | 1 | None | 140 | 200 | 22 | 3496 | 0.046 (0.007) | 0.011 (0.003) | 0.002 (0.001) | 0.048 (0.007) | 0.011 (0.003) | 0.002 (0.001) | PASS |
| f15m_tau20 | gate | feature | None | None | 15m | 1d | 1 | equal_weight | 1 | None | 520 | 20 | 22 | 3496 | 0.038 (0.007) | 0.005 (0.003) | 0.000 (0.001) | 0.040 (0.007) | 0.005 (0.003) | 0.000 (0.001) | PASS |
| f15m_tau200 | gate | feature | None | None | 15m | 1d | 1 | equal_weight | 1 | None | 520 | 200 | 22 | 3496 | 0.054 (0.007) | 0.007 (0.003) | 0.000 (0.001) | 0.058 (0.007) | 0.009 (0.003) | 0.000 (0.001) | PASS |
| f5m_tau20 | gate | feature | None | None | 5m | 1d | 1 | equal_weight | 1 | None | 1560 | 20 | 22 | 3496 | 0.057 (0.007) | 0.014 (0.003) | 0.005 (0.001) | 0.059 (0.007) | 0.017 (0.003) | 0.007 (0.001) | PASS |
| f5m_tau200 | gate | feature | None | None | 5m | 1d | 1 | equal_weight | 1 | None | 1560 | 200 | 22 | 3496 | 0.077 (0.007) | 0.014 (0.003) | 0.002 (0.001) | 0.079 (0.007) | 0.015 (0.003) | 0.002 (0.001) | FAIL |
| f1d_s5_tau5 | gate | feature | None | 5 | 1d | 1d | 1 | equal_weight | 1 | None | 252 | 5 | 321 | 3367 | 0.043 (0.007) | 0.008 (0.003) | 0.001 (0.001) | 0.046 (0.007) | 0.009 (0.003) | 0.001 (0.001) | PASS |
| f1d_s5_tau60 | gate | feature | None | 5 | 1d | 1d | 1 | equal_weight | 1 | None | 252 | 60 | 321 | 3367 | 0.046 (0.007) | 0.011 (0.003) | 0.000 (0.001) | 0.057 (0.007) | 0.015 (0.003) | 0.002 (0.001) | PASS |
| f1d_s21_tau5 | gate | feature | None | 21 | 1d | 1d | 1 | equal_weight | 1 | None | 252 | 5 | 534 | 3154 | 0.065 (0.007) | 0.008 (0.003) | 0.001 (0.001) | 0.071 (0.007) | 0.010 (0.003) | 0.001 (0.001) | FAIL |
| f1d_s21_tau60 | gate | feature | None | 21 | 1d | 1d | 1 | equal_weight | 1 | None | 252 | 60 | 534 | 3154 | 0.052 (0.007) | 0.006 (0.003) | 0.003 (0.001) | 0.066 (0.007) | 0.013 (0.003) | 0.004 (0.001) | PASS |
| f1d_s63_tau5 | gate | feature | None | 63 | 1d | 1d | 1 | equal_weight | 1 | None | 252 | 5 | 1092 | 2596 | 0.047 (0.007) | 0.013 (0.003) | 0.001 (0.001) | 0.071 (0.007) | 0.023 (0.003) | 0.005 (0.001) | FAIL |
| f1d_s63_tau60 | gate | feature | None | 63 | 1d | 1d | 1 | equal_weight | 1 | None | 252 | 60 | 1092 | 2596 | 0.050 (0.007) | 0.008 (0.003) | 0.001 (0.001) | 0.090 (0.007) | 0.024 (0.003) | 0.004 (0.001) | FAIL |
| f1h_s21_tau5 | gate | feature | None | 21 | 1h | 1d | 1 | equal_weight | 1 | None | 140 | 5 | 302 | 3386 | 0.066 (0.007) | 0.014 (0.003) | 0.007 (0.001) | 0.073 (0.007) | 0.015 (0.003) | 0.009 (0.001) | FAIL |
| rk_price_percentile_w126_1d | gate | rk_price_percentile | 126 | None | 1d | 1d | 1 | equal_weight | 1 | 2 | 125 | None | 127 | 3496 | 0.061 (0.007) | 0.012 (0.003) | 0.002 (0.001) | 0.068 (0.007) | 0.015 (0.003) | 0.004 (0.001) | FAIL |
| rk_high_dist_w126_1d | gate | rk_high_dist | 126 | None | 1d | 1d | 1 | equal_weight | 1 | 2 | 125 | None | 127 | 3496 | 0.046 (0.007) | 0.006 (0.003) | 0.003 (0.001) | 0.055 (0.007) | 0.013 (0.003) | 0.003 (0.001) | PASS |
| rk_vwap_dev_w20_1d | gate | rk_vwap_dev | 20 | None | 1d | 1d | 1 | equal_weight | 1 | 2 | 19 | None | 21 | 3496 | 0.046 (0.007) | 0.007 (0.003) | 0.000 (0.001) | 0.047 (0.007) | 0.007 (0.003) | 0.000 (0.001) | PASS |
| rk_vwap_dev_w20_1h | gate | rk_vwap_dev | 20 | None | 1h | 1d | 1 | equal_weight | 1 | 2 | 19 | None | 4 | 3496 | 0.053 (0.007) | 0.018 (0.003) | 0.005 (0.001) | 0.053 (0.007) | 0.017 (0.003) | 0.005 (0.001) | PASS |
| book1h_f1d_tau20 | gate | feature | None | None | 1d | 1h | 1 | equal_weight | 1 | None | 252 | 20 | 253 | 3435 | 0.054 (0.007) | 0.013 (0.003) | 0.003 (0.001) | 0.054 (0.007) | 0.013 (0.003) | 0.003 (0.001) | PASS |
| book1h_f1d_tau200 | gate | feature | None | None | 1d | 1h | 1 | equal_weight | 1 | None | 252 | 200 | 253 | 3435 | 0.083 (0.007) | 0.016 (0.003) | 0.003 (0.001) | 0.083 (0.007) | 0.016 (0.003) | 0.003 (0.001) | FAIL |
| hostile_tau200 | diag | feature | None | None | 1d | 1d | 1 | equal_weight | 1 | None | 252 | 200 | 254 | 3434 | 0.050 (0.007) | 0.009 (0.003) | 0.002 (0.001) | 0.072 (0.007) | 0.024 (0.003) | 0.006 (0.001) | FAIL |

## Certificates

Passing (every gating cell holds at 0.05 and 0.01 in both arms):

| identity | window | smoothing | source tf | book tf | memory bound (bars) |
|---|---|---|---|---|---|
| feature | none | none | 1h | 1d | 140 |
| feature | none | none | 15m | 1d | 520 |
| feature | none | 5 | 1d | 1d | 252 |
| rk_high_dist | 126 | none | 1d | 1d | 125 |
| rk_vwap_dev | 20 | none | 1d | 1d | 19 |
| rk_vwap_dev | 20 | none | 1h | 1d | 19 |

Failing (members needing these stay refused):

| identity | smoothing | source tf | book tf | failing gating cells |
|---|---|---|---|---|
| feature | none | 1d | 1d | f1d_tau60, f1d_tau200, f1d_static_tau200 |
| feature | none | 5m | 1d | f5m_tau200 |
| feature | 21 | 1d | 1d | f1d_s21_tau5 |
| feature | 63 | 1d | 1d | f1d_s63_tau5, f1d_s63_tau60 |
| feature | 21 | 1h | 1d | f1h_s21_tau5 |
| rk_price_percentile (126) | none | 1d | 1d | rk_price_percentile_w126_1d |
| feature | none | 1d | 1h | book1h_f1d_tau200 |

## Verdict

SIZE FAILS. Ten gating cells exceed the bound at 0.05 or 0.01 in at least one arm; none is reclassified. Six certificates pass and seven fail, listed above; pending todo `586` records the failure. The diagnostic cell `hostile_tau200` exceeds at 0.05 (book arm 72) and 0.01 (24) as the known E17 limit documents; it does not gate.

Pattern: oversize grows with predictor persistence. The sd of t in the book arm rises from 0.9-1.0 at tau 1-20 to 1.06 (tau 60) and 1.15 (tau 200); the member arm stays near 1.0 and fails only at 5m tau 200 and the hourly book. Long-memory smoothed cells (63-day half-life, 838 sessions) and the 1h book at tau 200 show the same shape. This is consistent with an HAC lag that does not scale with the persistence of the weights (todo 547's horizon-tied lag amendment is the related change); no fix is proposed here.

Power cost (Pitfall 8): mean tested sessions per cell are in the table (3,434 of 4,000 at memory 254; 2,596 at the 838-session smoother, 1,092 session L).
