# 184-05 persistent-predictor E17 battery report (D7 guard 6, B6)

Driver: `.venv/bin/python scripts/research/e17_null_battery.py 184-05-battery.json --battery src.intelligence.research.null_battery_persistent --sims 1000 --workers 6`

Battery module commit: 49e21bb41, kept reachable by tag `battery/184-05` (it was rebased to 9ceb891b6 on main, content-identical for the battery module, `families/features.py` and the driver: `git diff 49e21bb41 9ceb891b6` on those paths is empty) (clean certified code, no uncommitted change; the simulation code is unchanged in later commits, which only fill `PASSING_CERTIFICATES` and the refusal message). Record: 26 scenarios, 1,000 simulations each, 4,000-session panels, 60 names. The raw record is not committed (cells and counts are in the table).

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

## Withheld

The table above is unchanged evidence. Three of the six certificates it lists as passing are not admitted by the runner (todo 588, `WITHHELD_CERTIFICATES` in `null_battery_persistent.py`); `PASSING_CERTIFICATES` is the passing set minus these.

| certificate | cells | reason |
|---|---|---|
| feature, smoothing 5, 1d to 1d | f1d_s5_tau5, f1d_s5_tau60 | smoothing 5 on a 1d source passes only because the unsmoothed 1d to 1d route fails at tau 60 and 200 (persistence); it returns only if it passes at tau 200 |
| rk_vwap_dev 20, 1d to 1d | rk_vwap_dev_w20_1d | rk_vwap_dev 1d to 1d: the cells assume one volume basis; withheld until S0 supplies volume_basis and the battery certifies a mixed volume basis |
| rk_vwap_dev 20, 1h to 1d | rk_vwap_dev_w20_1h | rk_vwap_dev 1h to 1d: the cells assume one volume basis; withheld until S0 supplies volume_basis and the battery certifies a mixed volume basis |

The static gate is also per certificate and built from that certificate's cells only: no passing certificate has a static-stress cell, so each gates at 0 and a real panel with measurable static sizes is refused until todo 588 part B.

## Part B extension (todo 588)

Driver command: `.venv/bin/python scripts/research/e17_null_battery.py 588-b-battery.json --battery src.intelligence.research.null_battery_persistent --sims 1000 --workers 6 --seed-base 260000 --cells f1h_static1x_tau200,f1h_static2x_tau200,f15m_static1x_tau200,f15m_static2x_tau200,rk_high_dist_w126_1d_static1x,rk_high_dist_w126_1d_static2x,f1h_slot1x_tau200,f1h_slot2x_tau200,f15m_slot1x_tau200,f15m_slot2x_tau200,book_f1h_f15m_tau20,book_f1h_f15m_tau200,f1d_s5_tau200`

Battery module commit: eb6651a9f (clean, no uncommitted change to the certified code; the driver's `dirty_certified_code` is empty), kept reachable by tag `battery/588-b`. The 13 cells are appended after the 26 cells above, so the 184-05 table and its seeds are untouched. `--seed-base 260000` is 10,000 times the 26 earlier positions: each cell draws the seeds a full run would give it at its appended position. Record: 13 scenarios, 1,000 simulations each, 4,000-session panels, 60 names (the same conventions as 184-05). The raw record is not committed (cells and counts are in the tables). The run took 543 s on 6 workers. `f1h_tau200` and `f15m_tau200` are not rerun: their 184-05 results stand as the tau-200 cells of those two routes.

### Rule, fixed before the run

The 184-05 rule is unchanged: a gating cell holds size when the rejection count of every arm is at most 67 at 0.05 and 18 at 0.01 (`scipy.stats.binom.ppf(0.99, 1000, alpha)`); the 0.00167 column is descriptive and never gates. Three things the 184-05 text left open are set here:

1. A route certificate passes when every gating cell that carries only that route (no partner) passes, stress cells included. A failed stress cell would fail the route; none failed here.
2. A stress cell sets a ceiling: a certificate is admitted at a static size, or a time-of-day size, up to the largest stress its own passing cells held (`PASSED_STRESS_CELLS`, `static_gate` in `null_battery_persistent.py`). A route with no passed stress cell of a kind gates at 0 for that kind.
3. A two-member book is a composition. Its cells are judged on three arms: `member` (the 1h member), `member_b` (the 15m member) and `book_equal`. It is certified only when every one of its cells passes in every arm, and a book of several routes is gated at the minimum over its routes and its composition's own passed stress cells.

### Cells

Stress sizes are in idiosyncratic-sd units: static means at 1x and 2x `MEASURED_STATIC_CELL_SD` (0.019 and 0.038), time-of-day at 1x and 2x `MEASURED_SLOT_EFFECT_SD` (0.0096 and 0.0192). The book cells carry the 1h member's route in the identity columns; their partner is the 15m route (bound 520).

| cell | role | identity | window | smoothing_half_life | source_tf | book_tf | horizon | combiner | max_age_rows | max_gap_rows | source_memory_bars_max | tau (sessions) | L (sessions) | mean tested sessions | member 0.05 (se) | member 0.01 (se) | member 0.00167 (se, descriptive) | book 0.05 (se) | book 0.01 (se) | book 0.00167 (se, descriptive) | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| book_f1h_f15m_tau20 | gate | feature | None | None | 1h | 1d | 1 | equal_weight | 1 | None | 140 | 20 | 22 | 3496 | 0.045 (0.007) | 0.007 (0.003) | 0.000 (0.000) | 0.051 (0.007) | 0.010 (0.003) | 0.000 (0.000) | PASS |
| book_f1h_f15m_tau200 | gate | feature | None | None | 1h | 1d | 1 | equal_weight | 1 | None | 140 | 200 | 22 | 3496 | 0.048 (0.007) | 0.012 (0.003) | 0.001 (0.001) | 0.045 (0.007) | 0.009 (0.003) | 0.001 (0.001) | PASS |
| f15m_slot1x_tau200 | gate | feature | None | None | 15m | 1d | 1 | equal_weight | 1 | None | 520 | 200 | 22 | 3496 | 0.034 (0.006) | 0.004 (0.002) | 0.000 (0.000) | 0.037 (0.006) | 0.005 (0.002) | 0.001 (0.001) | PASS |
| f15m_slot2x_tau200 | gate | feature | None | None | 15m | 1d | 1 | equal_weight | 1 | None | 520 | 200 | 22 | 3496 | 0.045 (0.007) | 0.001 (0.001) | 0.000 (0.000) | 0.047 (0.007) | 0.002 (0.001) | 0.000 (0.000) | PASS |
| f15m_static1x_tau200 | gate | feature | None | None | 15m | 1d | 1 | equal_weight | 1 | None | 520 | 200 | 22 | 3496 | 0.049 (0.007) | 0.010 (0.003) | 0.000 (0.000) | 0.050 (0.007) | 0.010 (0.003) | 0.000 (0.000) | PASS |
| f15m_static2x_tau200 | gate | feature | None | None | 15m | 1d | 1 | equal_weight | 1 | None | 520 | 200 | 22 | 3496 | 0.051 (0.007) | 0.013 (0.004) | 0.001 (0.001) | 0.055 (0.007) | 0.014 (0.004) | 0.004 (0.002) | PASS |
| f1d_s5_tau200 | gate | feature | None | 5 | 1d | 1d | 1 | equal_weight | 1 | None | 252 | 200 | 321 | 3367 | 0.052 (0.007) | 0.010 (0.003) | 0.001 (0.001) | 0.070 (0.008) | 0.023 (0.005) | 0.006 (0.002) | FAIL |
| f1h_slot1x_tau200 | gate | feature | None | None | 1h | 1d | 1 | equal_weight | 1 | None | 140 | 200 | 22 | 3496 | 0.057 (0.007) | 0.016 (0.004) | 0.005 (0.002) | 0.062 (0.008) | 0.016 (0.004) | 0.005 (0.002) | PASS |
| f1h_slot2x_tau200 | gate | feature | None | None | 1h | 1d | 1 | equal_weight | 1 | None | 140 | 200 | 22 | 3496 | 0.051 (0.007) | 0.010 (0.003) | 0.000 (0.000) | 0.052 (0.007) | 0.010 (0.003) | 0.002 (0.001) | PASS |
| f1h_static1x_tau200 | gate | feature | None | None | 1h | 1d | 1 | equal_weight | 1 | None | 140 | 200 | 22 | 3496 | 0.048 (0.007) | 0.010 (0.003) | 0.003 (0.002) | 0.050 (0.007) | 0.011 (0.003) | 0.003 (0.002) | PASS |
| f1h_static2x_tau200 | gate | feature | None | None | 1h | 1d | 1 | equal_weight | 1 | None | 140 | 200 | 22 | 3496 | 0.060 (0.008) | 0.012 (0.003) | 0.002 (0.001) | 0.063 (0.008) | 0.012 (0.003) | 0.002 (0.001) | PASS |
| rk_high_dist_w126_1d_static1x | gate | rk_high_dist | 126 | None | 1d | 1d | 1 | equal_weight | 1 | 2 | 125 | None | 127 | 3496 | 0.040 (0.006) | 0.006 (0.002) | 0.001 (0.001) | 0.047 (0.007) | 0.007 (0.003) | 0.001 (0.001) | PASS |
| rk_high_dist_w126_1d_static2x | gate | rk_high_dist | 126 | None | 1d | 1d | 1 | equal_weight | 1 | 2 | 125 | None | 127 | 3496 | 0.045 (0.007) | 0.008 (0.003) | 0.000 (0.000) | 0.054 (0.007) | 0.011 (0.003) | 0.001 (0.001) | PASS |

The `member_b` arm of the two book cells: `book_f1h_f15m_tau20` 54 of 1,000 at 0.05, 16 at 0.01 (3 at 0.00167, descriptive); `book_f1h_f15m_tau200` 52, 9 and 1. All within the bounds.

### Notes on what the cells can see

- A daily book has one slot per session, so the time-of-day effect on these routes is a mean return common to every name (`static_sizes.measure` on a daily panel reads exactly that); the slot cells apply it as `DailyScenario.market_mean` on the null returns. The tau-200 feature cells carry the intraday source tf in their route (1h, 15m); a 1d source has no intraday slot and `rk_high_dist` 1d to 1d has no source-tf effect separate from its static means, so the kernel carries static cells only (the time-of-day cell for it is not applicable and is skipped).
- A kernel member has no tau (its price path sets its persistence, with a 126-session window), so a tau-200 cell for `rk_high_dist_w126_1d` has nothing to vary beyond the unstressed cell; none was added, and the two static cells are its additional evidence.
- The statistic is insensitive to these stresses by construction: at one fixed seed the 1h static cell gives an identical t at static sd 0.019, 0.038 and 0.3, and the slot cell an identical t at 0.0096 and 0.5 (dollar-neutral weights and the memory-lagged cell mean remove them). The stress cells are therefore independent replicates of the base size at each stress; the ceilings they earn are the sizes tested, not a sharper claim. Static means with volatility clustering remain the known limit that `hostile_tau200` documents.

### Verdicts

Twelve of thirteen gating cells hold size at 0.05 and 0.01 in every arm. One fails and stays a failure:

- `f1d_s5_tau200` (feature, smoothing 5, 1d to 1d, tau 200): book arm 70 of 1,000 at 0.05 (bound 67) and 23 at 0.01 (bound 18), sd of t 1.16. The member arm holds (52 and 10). Smoothing 5 does not return; it is not a passing route (todo 586 records it).

### Certificates after Part B

Passing routes and the largest size each held (static in units of the idiosyncratic sd; time-of-day likewise):

| identity | source tf | book tf | memory bound | static ceiling | time-of-day ceiling |
|---|---|---|---|---|---|
| feature | 1h | 1d | 140 | 0.038 (2x measured) | 0.0192 (2x measured) |
| feature | 15m | 1d | 520 | 0.038 (2x measured) | 0.0192 (2x measured) |
| rk_high_dist 126 | 1d | 1d | 125 | 0.038 (2x measured) | 0 (no cell) |

Certified composition: feature 1h to 1d with feature 15m to 1d, equal weight (cells `book_f1h_f15m_tau20`, `book_f1h_f15m_tau200`). Its own cells carry no stress, so a book of the two gates at 0 for both static and time-of-day; any other combination of input members, a repeated route, or three members stays refused.

Still refused: the smoothing-5 1d route (its tau-200 cell failed, above), the two `rk_vwap_dev` routes (withheld, unchanged), and the seven failing routes of the first table.
