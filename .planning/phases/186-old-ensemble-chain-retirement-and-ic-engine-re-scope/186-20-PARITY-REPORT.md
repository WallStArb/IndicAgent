# 186-20 parity report: stored POOLED cells versus the fresh IC function

Verdict: GATE NOT MET AS WRITTEN: 136 of 1080 cells differ from the stored value; every difference is attributed below. Generated 2026-10-01T07:58:41+00:00 by `tests/integration/test_ic_parity_replay.py` (read-only).

## Stated sample (fixed before running)

- Features: 30, chosen once with `random.Random(18620).sample(sorted(candidates), 30)`. Candidates are the FeatureVector fields that are numeric `feature_vectors` columns (dtype from information_schema), excluding concept_registry broadcast-flagged features and regime columns.
- Candidate accounting: {"feature_fields": 300, "numeric_fields": 300, "broadcast_excluded": 40, "regime_excluded": 5, "candidates": 255}. Broadcast-excluded count: 40.
- Sampled features: `sr_resist_dist`, `bars_since_extreme_move_fast`, `variance_ratio_momentum_product`, `garman_klass_vol_z`, `body_ratio`, `stoch_k_fast`, `fvg_dist_atr`, `smc_trend_direction`, `choch_direction`, `parkinson_vol_velocity`, `vwap_dev_sigma_velocity`, `prior_session_close_dist_atr`, `vol_range_ratio`, `range_position`, `ret_div_5m_1h`, `efficiency_volume_product`, `bars_since_vol_spike_fast`, `nearest_hvn_below_dist_atr`, `dist_from_high_fast`, `yield_slope_momentum_product`, `canary_noise_uniform`, `range_to_close`, `overnight_gap_z`, `sweep_strength`, `weekly_pivot_dist_atr`, `close_vs_open_direction`, `efficiency_ratio_slow`, `bars_since_52w_high`, `high_52w_dist`, `in_lvn`
- Timeframes and horizons: 5m {6,12,39}, 15m {2,5,10}, 1h {1,2}, 1d {1,2,5,10}. The 1h horizons 20 and 60 cross a session, have no kernel counterpart, and are excluded: 180 cells excluded (30 features x 2 horizons x 3 labels).
- Labels per tf (the 3 `regime_scope = 'cross_sectional'` labels with the most stored POOLED rows, ties alphabetical): 5m: down_secondary_backwardation (900 rows, group commodity), down_secondary_contango (900 rows, group commodity), down_secondary_neutral (900 rows, group commodity); 15m: down_primary_neutral (900 rows, group commodity), down_secondary_backwardation (900 rows, group commodity), down_secondary_contango (900 rows, group commodity); 1h: down_secondary_neutral (1200 rows, group commodity), up_secondary_neutral (1200 rows, group commodity), weak_dollar_risk_off (1200 rows, group fx); 1d: down_secondary_neutral (1200 rows, group commodity), up_secondary_neutral (1200 rows, group commodity), weak_dollar_risk_off (1200 rows, group fx)
- Cells: 30 features x 12 (tf, horizon) pairs x 3 labels = 1080 per replay pass; replayed: 1080. POOLED earnings_season cells share the machinery but are out of the sample.
- Point IC only; confidence intervals are RNG-dependent and out of parity scope (D-21).
- Peer symbols per (group/label): {"commodity/down_secondary_backwardation": 21, "commodity/down_secondary_contango": 21, "commodity/down_secondary_neutral": 21, "commodity/down_primary_neutral": 21, "commodity/up_secondary_neutral": 21, "fx/weak_dollar_risk_off": 12}

## Pass criterion (committed with the harness before any live result was read)

ic_engine stores `ic_value` as the result of `_vectorized_ic` on float32 ranks: every stored value is a float32 number, so 1e-9 absolute cannot hold for a faithful replay (float32 spacing at 0.0080 is 9.3e-10 and at 0.25 is 3e-8). The harness holds each cell to: stored `n_independent` equal exactly (a different row set cannot pass), stored NULL if and only if replay NaN, and `|replayed - stored| <= 2 * eps32 * ceil(log2(n_independent))` (the float32 pipeline's summation error bound, `float32_pipeline_tolerance`). The strict 1e-9 count is reported alongside. The writer-path cell below is float64 against float64 and is held to 1e-9.

## Table-target result

- Stored POOLED cross_sectional rows replayed: 1080; missing stored rows: 0.
- Cells matched (n_independent equal, NULL pattern equal, within the float32 bound): 944 of 1080; within the strict 1e-9: 44.
- Cells that differ: 136; unexplained: 0.
- Max abs delta over cells where both sides are finite: 4.566e-02.
- n_independent mismatches: 27, of which 0 are in cells whose feature has no non-finite value among the strided rows. The peer set, label bars, stride and target mask reproduce ic_engine's row set exactly where that count is zero; the other mismatches are partly-missing features, whose fresh count excludes the non-finite rows.
- Legacy-arithmetic replica (float32 features, a column with a non-finite value ranks NaN and stores 0.0, ranks before the target mask, float32 ranks, `_vectorized_ic`) reproduces the stored cell in 1078 of 1080 cells (n_independent is not part of that check).

| Cause | Cells | Max abs delta, fresh vs stored | Max abs fresh IC where stored 0.0 |
|---|---|---|---|
| reproduced | 944 | 4.220e-06 | 0.000e+00 |
| legacy_zero_ic_for_non_finite_feature | 66 | 4.566e-02 | 4.566e-02 |
| legacy_ranks_before_the_target_mask | 68 | 1.083e-04 | 0.000e+00 |
| float32_noise_beyond_the_committed_bound | 2 | 5.985e-06 | 0.000e+00 |
| unexplained | 0 | 0.000e+00 | 0.000e+00 |

Cells that differ by tf: {"5m": 14, "15m": 18, "1h": 12, "1d": 92}.
The legacy-zero cells are 39 all-missing columns (no finite value in the cell) and 27 partly-missing columns whose stored IC is 0.0 although a finite IC exists on the valid rows (the last column of the table).
Stored-NULL handling: 12 stored NULL, 12 replayed NaN; NULL-pattern mismatches: 39.
- First NULL mismatches: 15m/down_primary_neutral/ret_div_5m_1h/2; 15m/down_primary_neutral/ret_div_5m_1h/5; 15m/down_primary_neutral/ret_div_5m_1h/10; 15m/down_secondary_backwardation/ret_div_5m_1h/2; 15m/down_secondary_backwardation/ret_div_5m_1h/5; 15m/down_secondary_backwardation/ret_div_5m_1h/10; 15m/down_secondary_contango/ret_div_5m_1h/2; 15m/down_secondary_contango/ret_div_5m_1h/5; 15m/down_secondary_contango/ret_div_5m_1h/10; 1h/down_secondary_neutral/ret_div_5m_1h/1
- First n_independent mismatches: 5m/down_secondary_backwardation/nearest_hvn_below_dist_atr/6 stored 21470 replay 14034; 5m/down_secondary_backwardation/nearest_hvn_below_dist_atr/12 stored 10735 replay 7052; 5m/down_secondary_backwardation/nearest_hvn_below_dist_atr/39 stored 3304 replay 2172; 5m/down_secondary_contango/nearest_hvn_below_dist_atr/6 stored 20739 replay 14691; 5m/down_secondary_contango/nearest_hvn_below_dist_atr/12 stored 10370 replay 7414; 5m/down_secondary_contango/nearest_hvn_below_dist_atr/39 stored 3191 replay 2188; 5m/down_secondary_neutral/nearest_hvn_below_dist_atr/6 stored 507576 replay 356957; 5m/down_secondary_neutral/weekly_pivot_dist_atr/6 stored 507576 replay 507554; 5m/down_secondary_neutral/nearest_hvn_below_dist_atr/12 stored 253778 replay 178412; 5m/down_secondary_neutral/weekly_pivot_dist_atr/12 stored 253778 replay 253768

## Kernel-target attribution

Kernel targets are `panel.forward_returns` on S0 panels built with `end_exclusive = oos_start`, stacked as the 186-14 writer stacks them; the stride runs over `existing_rows(valid_grid, present)`.

- Target rows compared: 11735317; equal 8188631; end-of-window 0; gap 0; session-crossing 2772485; absent tradeable open 447977; other 326224. Session-crossing is an added cause: the kernel refuses an intraday return whose entry and exit opens sit in different sessions (D-18); the table keeps it. Absent tradeable open is an added cause too: the kernel's panel is built from `market_data_ohlcv_tradeable` (volume > 0), so an entry or exit open of a placeholder bar is NaN there while the table priced it.
- Cells where the kernel row set gives the table's n_independent: 267 of 1080.
- Max |kernel IC - table IC| over cells: 7.562e-02.
- Worst (tf, label, horizon) by differing rows: 5m/down_secondary_neutral/12 eow 0 gap 0 session 500781 open 130876 other 108373 of 3045577; 5m/down_secondary_neutral/39 eow 0 gap 0 session 1590960 open 89567 other 107202 of 3045577; 5m/down_secondary_neutral/6 eow 0 gap 0 session 251556 open 136512 other 77669 of 3045577; 5m/down_secondary_backwardation/39 eow 0 gap 0 session 34866 open 4439 other 6533 of 128820; 5m/down_secondary_contango/39 eow 0 gap 0 session 36834 open 4412 other 6051 of 124430

## Conclusion

Row-set parity holds: 0 cells whose feature is finite on the strided rows disagree on n_independent, so the peer set, label bars, stride and target mask rebuild ic_engine's cells exactly, and the legacy-arithmetic replica reproduces 1078 of 1080 stored values within the float32 bound.
Value parity as written (every sampled cell within tolerance) is NOT met: 136 of 1080 cells differ, all attributed. 66 stored ICs are 0.0 where a feature has a non-finite value among the strided rows (ic_engine's `rankdata` returns NaN for the column and `_vectorized_ic` maps a NaN denominator to 0.0; the fresh function drops the non-finite rows and the finite IC reaches 4.566e-02); 68 differ because ic_engine ranks X over every strided row before the target mask while the fresh function ranks the complete rows (max 1.083e-04); 2 exceed the committed float32 bound by float32 summation noise (fresh and replica agree).
Whether the unstratified pooled cell is justified per R-06 on this evidence is the gate decision the parity criterion leaves to the owner: the differences are defects of the stored legacy values (a zero IC for a partly-missing feature, a rank scope that is not Spearman on the complete sample), not of the fresh function, and the kernel-target differences are the causes counted above (0 end-of-window, 0 gap, 2772485 session-crossing exits refused by design, 447977 entry or exit opens absent from the tradeable panel, 326224 other).

## Re-deriving the stored numbers

```
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "select count(*) from feature_ic_scores"
-- 10616092 at the time of this run
select tf, regime, count(*) from feature_ic_scores where symbol='POOLED' and is_pooled and regime_scope='cross_sectional' group by 1,2 order by tf, count(*) desc, regime;
select ic_value, n_independent from feature_ic_scores where symbol='POOLED' and is_pooled and regime_scope='cross_sectional' and tf=:tf and regime=:label and feature_name=:feature and lookahead_bars=:horizon;
```

## Writer-path parity cell

<!-- BEGIN writer-path parity cell -->
(not yet computed)
<!-- END writer-path parity cell -->
