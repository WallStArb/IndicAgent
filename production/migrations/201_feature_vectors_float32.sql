-- Migration 201: feature_vectors float64 -> float32 (real) storage type
--
-- feature_vectors carried 156 double-precision feature columns across ~36M rows
-- (schema-data-types disk audit, 2026-07-09). Every consumer already truncates
-- these values to float32 in memory immediately on read:
--   - services/ic_engine.py:506,1257 (X_raw = np.array(..., dtype=np.float32),
--     "rank-based IC doesn't need float64 raw values")
--   - services/ensemble_trainer.py:731 (same fetch-shape fix as ic_engine's
--     commit 95a57806, "Empirically validated safe end-to-end... max relative
--     weight diff ~0.006%")
-- so storing float64 in the table added zero effective precision -- every value
-- already loses those bits on the next read. Spot-checked value ranges
-- (momentum_z_fast, hurst, vwap_dev_sigma, rsi_fast, shannon, dollar_vol_z,
-- obv_z, vol_of_vol) all sit well inside float32's range and >7-significant-digit
-- precision; these are z-scores/ratios/probabilities, not accumulator sums.
--
-- TimescaleDB refuses ALTER COLUMN TYPE on a hypertable with compressed chunks
-- ("operation not supported on hypertables with compressed chunks", confirmed
-- via a rolled-back test), so this decompresses every chunk, rewrites all 156
-- columns in one pass, then recompresses. compression_settings (segmentby
-- symbol/tf, orderby bar_ts) are untouched since none of the altered columns
-- participate in them.
--
-- Expected effect: roughly halves the ~52GB raw (pre-compression) footprint of
-- these columns; compounds with the compression already in place (measured
-- 1.68x on the float64 data during the same disk audit).

BEGIN;

DO $$
DECLARE
  c record;
BEGIN
  FOR c IN
    SELECT format('%I.%I', chunk_schema, chunk_name)::regclass AS chunk
    FROM timescaledb_information.chunks
    WHERE hypertable_name = 'feature_vectors' AND is_compressed
  LOOP
    PERFORM decompress_chunk(c.chunk);
  END LOOP;
END $$;

ALTER TABLE feature_vectors
    ALTER COLUMN above_wk_vwap TYPE real USING above_wk_vwap::real,
    ALTER COLUMN adx TYPE real USING adx::real,
    ALTER COLUMN amihud_illiq_z TYPE real USING amihud_illiq_z::real,
    ALTER COLUMN aroon_fast TYPE real USING aroon_fast::real,
    ALTER COLUMN aroon_slow TYPE real USING aroon_slow::real,
    ALTER COLUMN atr_z TYPE real USING atr_z::real,
    ALTER COLUMN bar_close_pos TYPE real USING bar_close_pos::real,
    ALTER COLUMN bb_pct_b_fast TYPE real USING bb_pct_b_fast::real,
    ALTER COLUMN bb_pct_b_slow TYPE real USING bb_pct_b_slow::real,
    ALTER COLUMN body_ratio TYPE real USING body_ratio::real,
    ALTER COLUMN cci_fast TYPE real USING cci_fast::real,
    ALTER COLUMN cci_mid TYPE real USING cci_mid::real,
    ALTER COLUMN cci_slow TYPE real USING cci_slow::real,
    ALTER COLUMN close_vs_open_direction TYPE real USING close_vs_open_direction::real,
    ALTER COLUMN cmf TYPE real USING cmf::real,
    ALTER COLUMN ctf_momentum TYPE real USING ctf_momentum::real,
    ALTER COLUMN ctf_regime_align TYPE real USING ctf_regime_align::real,
    ALTER COLUMN ctf_vwap_align TYPE real USING ctf_vwap_align::real,
    ALTER COLUMN cvd_slope_z TYPE real USING cvd_slope_z::real,
    ALTER COLUMN day_of_month_cos TYPE real USING day_of_month_cos::real,
    ALTER COLUMN day_of_month_sin TYPE real USING day_of_month_sin::real,
    ALTER COLUMN days_to_month_end TYPE real USING days_to_month_end::real,
    ALTER COLUMN dist_from_high_fast TYPE real USING dist_from_high_fast::real,
    ALTER COLUMN dist_from_high_slow TYPE real USING dist_from_high_slow::real,
    ALTER COLUMN dist_from_low_fast TYPE real USING dist_from_low_fast::real,
    ALTER COLUMN dist_from_low_slow TYPE real USING dist_from_low_slow::real,
    ALTER COLUMN dollar_vol_z TYPE real USING dollar_vol_z::real,
    ALTER COLUMN dow_cos TYPE real USING dow_cos::real,
    ALTER COLUMN dow_sin TYPE real USING dow_sin::real,
    ALTER COLUMN efficiency_ratio_fast TYPE real USING efficiency_ratio_fast::real,
    ALTER COLUMN efficiency_ratio_slow TYPE real USING efficiency_ratio_slow::real,
    ALTER COLUMN flight_quality TYPE real USING flight_quality::real,
    ALTER COLUMN gap_z TYPE real USING gap_z::real,
    ALTER COLUMN garch_ratio TYPE real USING garch_ratio::real,
    ALTER COLUMN garman_klass_vol_velocity TYPE real USING garman_klass_vol_velocity::real,
    ALTER COLUMN garman_klass_vol_z TYPE real USING garman_klass_vol_z::real,
    ALTER COLUMN high_52w_dist TYPE real USING high_52w_dist::real,
    ALTER COLUMN high_low_corr TYPE real USING high_low_corr::real,
    ALTER COLUMN hma_slope_z TYPE real USING hma_slope_z::real,
    ALTER COLUMN hmm_churn TYPE real USING hmm_churn::real,
    ALTER COLUMN hmm_duration TYPE real USING hmm_duration::real,
    ALTER COLUMN hmm_entropy TYPE real USING hmm_entropy::real,
    ALTER COLUMN hmm_prob_ranging TYPE real USING hmm_prob_ranging::real,
    ALTER COLUMN hmm_prob_trending_down TYPE real USING hmm_prob_trending_down::real,
    ALTER COLUMN hmm_prob_trending_up TYPE real USING hmm_prob_trending_up::real,
    ALTER COLUMN hmm_regime_prob TYPE real USING hmm_regime_prob::real,
    ALTER COLUMN hour_of_day_cos TYPE real USING hour_of_day_cos::real,
    ALTER COLUMN hour_of_day_sin TYPE real USING hour_of_day_sin::real,
    ALTER COLUMN hurst TYPE real USING hurst::real,
    ALTER COLUMN hv_ratio TYPE real USING hv_ratio::real,
    ALTER COLUMN hv_z_fast TYPE real USING hv_z_fast::real,
    ALTER COLUMN hv_z_slow TYPE real USING hv_z_slow::real,
    ALTER COLUMN in_london_kz TYPE real USING in_london_kz::real,
    ALTER COLUMN in_ny_session TYPE real USING in_ny_session::real,
    ALTER COLUMN in_overlap TYPE real USING in_overlap::real,
    ALTER COLUMN informed_flow TYPE real USING informed_flow::real,
    ALTER COLUMN intraday_noise_ratio TYPE real USING intraday_noise_ratio::real,
    ALTER COLUMN intraday_ret TYPE real USING intraday_ret::real,
    ALTER COLUMN lower_wick_ratio TYPE real USING lower_wick_ratio::real,
    ALTER COLUMN mfi_fast TYPE real USING mfi_fast::real,
    ALTER COLUMN mfi_slow TYPE real USING mfi_slow::real,
    ALTER COLUMN momentum_rank_z TYPE real USING momentum_rank_z::real,
    ALTER COLUMN momentum_reversal_z TYPE real USING momentum_reversal_z::real,
    ALTER COLUMN momentum_z_fast TYPE real USING momentum_z_fast::real,
    ALTER COLUMN momentum_z_mid TYPE real USING momentum_z_mid::real,
    ALTER COLUMN momentum_z_slow TYPE real USING momentum_z_slow::real,
    ALTER COLUMN month_cos TYPE real USING month_cos::real,
    ALTER COLUMN month_position TYPE real USING month_position::real,
    ALTER COLUMN month_sin TYPE real USING month_sin::real,
    ALTER COLUMN new_high_flag TYPE real USING new_high_flag::real,
    ALTER COLUMN new_low_flag TYPE real USING new_low_flag::real,
    ALTER COLUMN obv_z TYPE real USING obv_z::real,
    ALTER COLUMN ofi_div TYPE real USING ofi_div::real,
    ALTER COLUMN ofi_z TYPE real USING ofi_z::real,
    ALTER COLUMN open_ret TYPE real USING open_ret::real,
    ALTER COLUMN open_vs_intraday TYPE real USING open_vs_intraday::real,
    ALTER COLUMN opening_range TYPE real USING opening_range::real,
    ALTER COLUMN overnight_gap TYPE real USING overnight_gap::real,
    ALTER COLUMN overnight_gap_z TYPE real USING overnight_gap_z::real,
    ALTER COLUMN parkinson_vol_velocity TYPE real USING parkinson_vol_velocity::real,
    ALTER COLUMN parkinson_vol_z TYPE real USING parkinson_vol_z::real,
    ALTER COLUMN poc_dist_atr TYPE real USING poc_dist_atr::real,
    ALTER COLUMN power_hour TYPE real USING power_hour::real,
    ALTER COLUMN price_percentile_fast TYPE real USING price_percentile_fast::real,
    ALTER COLUMN price_percentile_slow TYPE real USING price_percentile_slow::real,
    ALTER COLUMN price_vol_corr_fast TYPE real USING price_vol_corr_fast::real,
    ALTER COLUMN price_vol_corr_slow TYPE real USING price_vol_corr_slow::real,
    ALTER COLUMN quarter_position TYPE real USING quarter_position::real,
    ALTER COLUMN range_efficiency TYPE real USING range_efficiency::real,
    ALTER COLUMN range_pct_fast TYPE real USING range_pct_fast::real,
    ALTER COLUMN range_pct_slow TYPE real USING range_pct_slow::real,
    ALTER COLUMN range_position TYPE real USING range_position::real,
    ALTER COLUMN range_to_close TYPE real USING range_to_close::real,
    ALTER COLUMN range_vol_product TYPE real USING range_vol_product::real,
    ALTER COLUMN range_vs_atr TYPE real USING range_vs_atr::real,
    ALTER COLUMN realized_var_ratio_fast TYPE real USING realized_var_ratio_fast::real,
    ALTER COLUMN realized_var_ratio_slow TYPE real USING realized_var_ratio_slow::real,
    ALTER COLUMN rel_volume TYPE real USING rel_volume::real,
    ALTER COLUMN ret_acf1_z TYPE real USING ret_acf1_z::real,
    ALTER COLUMN ret_autocorr_1 TYPE real USING ret_autocorr_1::real,
    ALTER COLUMN ret_autocorr_5 TYPE real USING ret_autocorr_5::real,
    ALTER COLUMN ret_kurtosis_z_fast TYPE real USING ret_kurtosis_z_fast::real,
    ALTER COLUMN ret_kurtosis_z_slow TYPE real USING ret_kurtosis_z_slow::real,
    ALTER COLUMN ret_lag_1 TYPE real USING ret_lag_1::real,
    ALTER COLUMN ret_lag_2 TYPE real USING ret_lag_2::real,
    ALTER COLUMN ret_lag_3 TYPE real USING ret_lag_3::real,
    ALTER COLUMN ret_lag_fast TYPE real USING ret_lag_fast::real,
    ALTER COLUMN ret_lag_mid TYPE real USING ret_lag_mid::real,
    ALTER COLUMN ret_lag_slow TYPE real USING ret_lag_slow::real,
    ALTER COLUMN ret_skew_z TYPE real USING ret_skew_z::real,
    ALTER COLUMN ret_vol_product_fast TYPE real USING ret_vol_product_fast::real,
    ALTER COLUMN ret_vol_ratio_fast TYPE real USING ret_vol_ratio_fast::real,
    ALTER COLUMN rsi_fast TYPE real USING rsi_fast::real,
    ALTER COLUMN rsi_mid TYPE real USING rsi_mid::real,
    ALTER COLUMN rsi_slow TYPE real USING rsi_slow::real,
    ALTER COLUMN session_time_pos TYPE real USING session_time_pos::real,
    ALTER COLUMN shannon TYPE real USING shannon::real,
    ALTER COLUMN sr_resist_dist TYPE real USING sr_resist_dist::real,
    ALTER COLUMN sr_support_dist TYPE real USING sr_support_dist::real,
    ALTER COLUMN stoch_k_fast TYPE real USING stoch_k_fast::real,
    ALTER COLUMN stoch_k_slow TYPE real USING stoch_k_slow::real,
    ALTER COLUMN streak_z TYPE real USING streak_z::real,
    ALTER COLUMN true_range_pct TYPE real USING true_range_pct::real,
    ALTER COLUMN up_vol_body_diff TYPE real USING up_vol_body_diff::real,
    ALTER COLUMN up_vol_ratio_fast TYPE real USING up_vol_ratio_fast::real,
    ALTER COLUMN up_vol_ratio_slow TYPE real USING up_vol_ratio_slow::real,
    ALTER COLUMN updown_ratio_fast TYPE real USING updown_ratio_fast::real,
    ALTER COLUMN updown_ratio_slow TYPE real USING updown_ratio_slow::real,
    ALTER COLUMN upper_wick_ratio TYPE real USING upper_wick_ratio::real,
    ALTER COLUMN va_position TYPE real USING va_position::real,
    ALTER COLUMN variance_ratio_fast TYPE real USING variance_ratio_fast::real,
    ALTER COLUMN variance_ratio_slow TYPE real USING variance_ratio_slow::real,
    ALTER COLUMN vix_z TYPE real USING vix_z::real,
    ALTER COLUMN vol_acceleration TYPE real USING vol_acceleration::real,
    ALTER COLUMN vol_asymmetry_z TYPE real USING vol_asymmetry_z::real,
    ALTER COLUMN vol_body_product TYPE real USING vol_body_product::real,
    ALTER COLUMN vol_of_vol TYPE real USING vol_of_vol::real,
    ALTER COLUMN vol_percentile TYPE real USING vol_percentile::real,
    ALTER COLUMN vol_persistence TYPE real USING vol_persistence::real,
    ALTER COLUMN vol_range_ratio TYPE real USING vol_range_ratio::real,
    ALTER COLUMN vol_ratio TYPE real USING vol_ratio::real,
    ALTER COLUMN vol_skew_product TYPE real USING vol_skew_product::real,
    ALTER COLUMN vol_std_z TYPE real USING vol_std_z::real,
    ALTER COLUMN vol_trend_ratio TYPE real USING vol_trend_ratio::real,
    ALTER COLUMN vol_velocity_z TYPE real USING vol_velocity_z::real,
    ALTER COLUMN volatility_rank_z TYPE real USING volatility_rank_z::real,
    ALTER COLUMN volume_rank_z TYPE real USING volume_rank_z::real,
    ALTER COLUMN volume_z TYPE real USING volume_z::real,
    ALTER COLUMN vwap_dev_sigma TYPE real USING vwap_dev_sigma::real,
    ALTER COLUMN week_of_month_cos TYPE real USING week_of_month_cos::real,
    ALTER COLUMN week_of_month_sin TYPE real USING week_of_month_sin::real,
    ALTER COLUMN week_of_year_cos TYPE real USING week_of_year_cos::real,
    ALTER COLUMN week_of_year_sin TYPE real USING week_of_year_sin::real,
    ALTER COLUMN yang_zhang_vol_velocity TYPE real USING yang_zhang_vol_velocity::real,
    ALTER COLUMN yang_zhang_vol_z TYPE real USING yang_zhang_vol_z::real,
    ALTER COLUMN yield_slope_z TYPE real USING yield_slope_z::real;

COMMIT;

-- Recompression is intentionally a separate statement (outside the DDL
-- transaction): compress_chunk() takes its own per-chunk locks and this way a
-- failure partway through recompression can't roll back the (already-verified)
-- type change.
DO $$
DECLARE
  c record;
BEGIN
  FOR c IN
    SELECT format('%I.%I', chunk_schema, chunk_name)::regclass AS chunk
    FROM timescaledb_information.chunks
    WHERE hypertable_name = 'feature_vectors' AND NOT is_compressed
  LOOP
    PERFORM compress_chunk(c.chunk);
  END LOOP;
END $$;

-- MANDATORY, not optional: compress_chunk() moves rows into the compressed
-- columnar store but does not synchronously reclaim the decompressed heap
-- pages decompress_chunk() populated above -- that reclamation only happens
-- when something VACUUMs the chunk, and these internal chunk tables are not
-- guaranteed to get picked up promptly by autovacuum. Migration 312 repeated
-- this file's pattern without this step and it turned into a 768GB->57GB disk
-- incident on 2026-08-13 (confirmed via VACUUM VERBOSE: 0 live tuples, never
-- vacuumed, full pre-migration footprint still on disk under the correctly-
-- compressed data). Added retroactively so this file is correct if ever
-- replayed. See docs/foundation/timescaledb-compressed-column-migration.md.
-- Cannot run inside a transaction block, so this must stay a bare top-level
-- statement after the DO block above, never wrapped in BEGIN/COMMIT.
VACUUM feature_vectors;
