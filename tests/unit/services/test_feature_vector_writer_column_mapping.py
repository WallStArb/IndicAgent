"""Regression test pinning the column mapping in _record_to_insert_params.

Verifies that the tuple produced by _record_to_insert_params
carries data in the correct position for each INSERT column.
Migration 159 expanded the tuple from 61 to 70 elements; migration 206's
2026-07-08 persistence-wiring fix (see feature_vector_persistence.py
docstring) extended it to 161 (159 post migration 211's redundant-field
drop); migration 223 extended it to 164 (5 canary columns); migration 255
(Phase 163 Plan 01) extended it to 181 (17 structural VP/SR columns,
appended after the canary fields); migration 266 (Phase 164 Plan 01)
extended it to 217 (36 SMC institutional-footprint columns, appended after
the structural VP/SR fields); migration 267 (Phase 165 Plan 01) extended it
to 258 (41 swing/fib/trend/session structure columns, appended after the SMC
fields):

  $1   (params[0])   -> feature_vector_id       UUID (content-key)
  $2   (params[1])   -> symbol                  str
  $3   (params[2])   -> tf                      str
  $4   (params[3])   -> bar_ts                  datetime
  $5   (params[4])   -> pipeline_version        str
  $6   (params[5])   -> feature_factory_version str  (NEW in 138-P1)
  $7   (params[6])   -> regime                  str | None
  $8   (params[7])   -> regime_label_source     str
  $9   (params[8])   -> momentum_z_fast         float
  $22  (params[21])  -> atr_z                   float
  $31  (params[30])  -> hurst                   float
  $56  (params[55])  -> ctf_momentum            float
  $62  (params[61])  -> ret_acf1_z              float
  $63  (params[62])  -> bar_close_ts            datetime  (NEW in 138-P1)
  $70  (params[69])  -> volatility_rank_z       float | None  (NEW in 138-P1)
  $71  (params[70])  -> body_ratio              float  (NEW in migration 206)
  $161 (params[160]) -> vol_skew_product        float  (NEW in migration 206, last column)

This test will fail if any column shift occurs in _record_to_insert_params.
"""

import uuid
from datetime import UTC, datetime

import pytest


def _make_sentinel_record():
    """Build a FeatureVectorRecord with distinguishable sentinel values per field group."""
    from src.intelligence.schemas import FeatureVector, FeatureVectorRecord

    fv = FeatureVector(
        momentum_z_fast=1.111,
        momentum_z_mid=2.222,
        range_position=3.333,
        bar_close_pos=4.444,
        gap_z=5.555,
        momentum_z_slow=6.601,
        momentum_reversal_z=6.602,
        informed_flow=6.666,
        volume_z=7.777,
        ofi_z=8.888,
        ofi_div=9.999,
        cvd_slope_z=10.10,
        cmf=11.11,
        rel_volume=12.12,
        vwap_dev_sigma=13.13,
        atr_z=14.14,
        vol_ratio=15.15,
        poc_dist_atr=16.16,
        va_position=17.17,
        sr_support_dist=18.18,
        sr_resist_dist=19.19,
        # Structural VP/SR (Phase 163 Plan 01) — wired into the persisted tuple
        # 2026-07-23 (migration 255 writer wiring), appended after the canary
        # fields (see feature_vector_persistence.py docstring).
        nearest_hvn_above_dist_atr=61.01,
        nearest_hvn_below_dist_atr=61.02,
        nearest_lvn_above_dist_atr=61.03,
        nearest_lvn_below_dist_atr=61.04,
        price_in_value_area=61.05,
        in_lvn=61.06,
        va_width_atr=61.07,
        distance_to_vah_atr=61.08,
        distance_to_val_atr=61.09,
        nearest_hvn_dist_atr=61.10,
        poc_rolling_dist_atr=61.11,
        poc_session_rolling_divergence_atr=61.12,
        resistance_strength=61.13,
        support_strength=61.14,
        resistance_age_bars=61.15,
        support_age_bars=61.16,
        sr_level_count=61.17,
        hmm_regime_prob=20.20,
        hmm_entropy=21.21,
        hmm_duration=22.22,
        hurst=23.23,
        shannon=24.24,
        garch_ratio=25.25,
        hma_slope_z=26.26,
        adx=27.27,
        aroon_fast=28.28,
        aroon_slow=29.29,
        rsi_fast=30.30,
        rsi_mid=31.31,
        rsi_slow=32.32,
        cci_fast=33.33,
        cci_mid=34.34,
        cci_slow=35.35,
        vix_z=36.36,
        flight_quality=37.37,
        yield_slope_z=38.38,
        in_ny_session=39.39,
        in_london_kz=40.40,
        in_overlap=41.41,
        power_hour=42.42,
        opening_range=43.43,
        above_wk_vwap=44.44,
        dow_sin=45.45,
        dow_cos=46.46,
        month_position=47.47,
        quarter_position=47.48,
        days_to_month_end=47.49,
        # Calendar Cycle/TDOM/Minute + Velocity (Phase 151 Plan 01) — not yet
        # in the persisted tuple (migration lands with Plan 01 Task 2/3);
        # construction requires these non-optional fields.
        quarter_cycle_sin=47.50,
        quarter_cycle_cos=47.51,
        tdom_sin=47.52,
        tdom_cos=47.53,
        minute_of_hour_sin=47.54,
        minute_of_hour_cos=47.55,
        ctf_momentum=48.48,
        ctf_vwap_align=49.49,
        ctf_regime_align=50.50,
        amihud_illiq_z=51.51,
        high_52w_dist=52.52,
        ret_skew_z=53.53,
        ret_acf1_z=54.54,
        # Renaissance Primitives (Phase 142.5 Plan 01) — wired into the persisted
        # tuple 2026-07-08 (migration 206 writer wiring).
        body_ratio=55.01,
        upper_wick_ratio=55.02,
        lower_wick_ratio=55.03,
        range_vs_atr=55.04,
        close_vs_open_direction=55.05,
        overnight_gap=55.06,
        overnight_gap_z=55.07,
        range_efficiency=55.08,
        ret_lag_1=55.09,
        ret_lag_2=55.10,
        ret_lag_3=55.11,
        ret_lag_fast=55.12,
        ret_lag_mid=55.13,
        ret_lag_slow=55.14,
        open_ret=55.15,
        intraday_ret=55.16,
        open_vs_intraday=55.17,
        session_time_pos=55.18,
        # Renaissance Primitives (Phase 142.5 Plan 02) — wired into the persisted
        # tuple 2026-07-08 (migration 206 writer wiring).
        hour_of_day_sin=56.01,
        hour_of_day_cos=56.02,
        week_of_month_sin=56.03,
        week_of_month_cos=56.04,
        day_of_month_sin=56.05,
        day_of_month_cos=56.06,
        week_of_year_sin=56.07,
        week_of_year_cos=56.08,
        month_sin=56.09,
        month_cos=56.10,
        vol_acceleration=56.11,
        dollar_vol_z=56.12,
        vol_range_ratio=56.13,
        vol_trend_ratio=56.14,
        up_vol_ratio_fast=56.15,
        up_vol_ratio_slow=56.16,
        vol_percentile=56.17,
        vol_persistence=56.18,
        vol_std_z=56.19,
        mfi_fast=56.20,
        mfi_slow=56.21,
        obv_z=56.22,
        # Renaissance Primitives (Phase 142.5 Plan 05) — wired into the persisted
        # tuple 2026-07-08 (migration 206 writer wiring).
        dist_from_high_fast=57.01,
        dist_from_high_slow=57.02,
        dist_from_low_fast=57.03,
        dist_from_low_slow=57.04,
        range_pct_fast=57.05,
        range_pct_slow=57.06,
        stoch_k_fast=57.09,
        stoch_k_slow=57.10,
        price_percentile_fast=57.11,
        price_percentile_slow=57.12,
        efficiency_ratio_fast=57.13,
        efficiency_ratio_slow=57.14,
        # Renaissance Primitives (Phase 142.5 Plan 03) — wired into the persisted
        # tuple 2026-07-08 (migration 206 writer wiring).
        ret_kurtosis_z_fast=58.01,
        ret_kurtosis_z_slow=58.02,
        ret_autocorr_1=58.03,
        ret_autocorr_5=58.04,
        updown_ratio_fast=58.05,
        updown_ratio_slow=58.06,
        streak_z=58.07,
        realized_var_ratio_fast=58.08,
        realized_var_ratio_slow=58.09,
        range_to_close=58.10,
        true_range_pct=58.11,
        vol_of_vol=58.12,
        high_low_corr=58.13,
        variance_ratio_fast=58.14,
        variance_ratio_slow=58.15,
        vol_asymmetry_z=58.16,
        bb_pct_b_fast=58.17,
        bb_pct_b_slow=58.18,
        hv_z_fast=58.19,
        hv_z_slow=58.20,
        hv_ratio=58.21,
        # Renaissance Primitives (Phase 142.5 Plan 04) — wired into the persisted
        # tuple 2026-07-08 (migration 206 writer wiring).
        parkinson_vol_z=59.01,
        garman_klass_vol_z=59.02,
        yang_zhang_vol_z=59.03,
        parkinson_vol_velocity=59.04,
        garman_klass_vol_velocity=59.05,
        yang_zhang_vol_velocity=59.06,
        vol_velocity_z=59.07,
        intraday_noise_ratio=59.08,
        # Renaissance Primitives (Phase 142.5 Plan 05.5) — wired into the
        # persisted tuple 2026-07-08 (migration 206 writer wiring).
        vol_body_product=60.01,
        ret_vol_product_fast=60.02,
        price_vol_corr_fast=60.03,
        price_vol_corr_slow=60.04,
        range_vol_product=60.05,
        up_vol_body_diff=60.06,
        ret_vol_ratio_fast=60.07,
        vol_skew_product=60.08,
        # Swing/Fib/Trend/Session Structure (Phase 165 Plan 01) — construction
        # requires these non-optional fields; nullable so None is valid.
        # None here since these are contract-only placeholders (Plans 02-04
        # wire real compute logic).
        swing_high_dist_atr=None,
        swing_low_dist_atr=None,
        swing_high_type=None,
        swing_low_type=None,
        swing_pattern=None,
        swing_high_age_bars=None,
        swing_low_age_bars=None,
        trend_direction=None,
        trend_strength=None,
        trend_leg_count=None,
        structure_integrity=None,
        price_position=None,
        trend_duration_bars=None,
        swing_amplitude_ratio=None,
        swing_amplitude_expanding=None,
        swing_amplitude_intensity=None,
        swing_velocity_bars=None,
        swing_velocity_bias=None,
        struct_energy=None,
        struct_accel_bias=None,
        swing_volume_confirmation=None,
        nearest_fib_ratio=None,
        nearest_fib_dist_atr=None,
        fib_cluster_strength=None,
        in_fib_discount_zone=None,
        prior_session_high_dist_atr=None,
        prior_session_low_dist_atr=None,
        prior_session_close_dist_atr=None,
        overnight_high_dist_atr=None,
        overnight_low_dist_atr=None,
        overnight_range_pct=None,
        opening_gap_pct=None,
        weekly_pivot_dist_atr=None,
        weekly_r1_dist_atr=None,
        weekly_r2_dist_atr=None,
        weekly_s1_dist_atr=None,
        weekly_s2_dist_atr=None,
        nearest_level_dist_atr=None,
        asian_session_high_dist_atr=None,
        asian_session_low_dist_atr=None,
        gap_filled=None,
    )
    return FeatureVectorRecord(
        symbol="SPY",
        tf="1h",
        bar_ts=datetime(2026, 6, 22, 14, 0, 0, tzinfo=UTC),
        pipeline_version="3.0.0",
        feature_factory_version="1.0.0",
        regime="trending_up",
        regime_label_source="filtered",
        vector=fv,
    )


def test_params_length_is_159():
    """_record_to_insert_params must return exactly 258 elements (159 post migration
    211's new_high_flag/new_low_flag drop, 164 after migration 223's 5 canary
    columns, 181 after migration 255's 17 structural VP/SR columns, 217 after
    migration 266's 36 SMC institutional-footprint columns, 258 after
    migration 267's 41 swing/fib/trend/session structure columns — see
    feature_vector_persistence.py docstring)."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert len(params) == 258, f"Expected 258, got {len(params)}"


def test_feature_vector_id_at_index_0():
    """params[0] ($1) must be a UUID — the content-key."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert isinstance(params[0], uuid.UUID), f"$1 must be UUID, got {type(params[0])}"


def test_symbol_at_index_1():
    """params[1] ($2) must be the symbol string."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert params[1] == "SPY", f"$2 must be 'SPY', got {params[1]}"


def test_tf_at_index_2():
    """params[2] ($3) must be the timeframe string."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert params[2] == "1h", f"$3 must be '1h', got {params[2]}"


def test_bar_ts_at_index_3():
    """params[3] ($4) must be a datetime."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert isinstance(params[3], datetime), f"$4 must be datetime, got {type(params[3])}"


def test_pipeline_version_at_index_4():
    """params[4] ($5) must be the pipeline_version string."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert params[4] == "3.0.0", f"$5 must be '3.0.0', got {params[4]}"


def test_feature_factory_version_at_index_5():
    """params[5] ($6) must be feature_factory_version (NEW in 138-P1, Task 6)."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert params[5] == "1.0.0", f"$6 must be '1.0.0', got {params[5]}"


def test_regime_at_index_6():
    """params[6] ($7) must be the regime string (shifted by 1 from 138-P1)."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert params[6] == "trending_up", f"$7 must be 'trending_up', got {params[6]}"


def test_momentum_z_fast_at_index_8():
    """params[8] ($9) must be momentum_z_fast sentinel value 1.111."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert params[8] == pytest.approx(1.111), f"$9 (momentum_z_fast) wrong: {params[8]}"


def test_atr_z_at_index_21():
    """params[21] ($22) must be atr_z sentinel value 14.14."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert params[21] == pytest.approx(14.14), f"$22 (atr_z) wrong: {params[21]}"


def test_hurst_at_index_30():
    """params[30] ($31) must be hurst sentinel value 23.23."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert params[30] == pytest.approx(23.23), f"$31 (hurst) wrong: {params[30]}"


def test_ctf_momentum_at_index_55():
    """params[55] ($56) must be ctf_momentum sentinel value 48.48."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert params[55] == pytest.approx(48.48), f"$56 (ctf_momentum) wrong: {params[55]}"


def test_ret_acf1_z_at_index_61():
    """params[61] ($62) must be ret_acf1_z sentinel value 54.54."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert params[61] == pytest.approx(54.54), f"$62 (ret_acf1_z) wrong: {params[61]}"


def test_bar_close_ts_at_index_62():
    """params[62] ($63) must be bar_close_ts (datetime, computed as bar_ts + 1h)."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    # tf='1h' => bar_close_ts = bar_ts + 3600s
    expected = datetime(2026, 6, 22, 15, 0, 0, tzinfo=UTC)
    assert isinstance(params[62], datetime), f"$63 must be datetime, got {type(params[62])}"
    assert params[62] == expected, f"$63 (bar_close_ts) wrong: {params[62]}"


def test_volatility_rank_z_at_index_69():
    """params[69] ($70) must be volatility_rank_z (None for cross-sectional fields)."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert params[69] is None, f"$70 (volatility_rank_z) must be None, got {params[69]}"


def test_no_cross_contamination_between_feature_groups():
    """Verify momentum sentinel does not leak into vol_ratio position."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    # momentum_z_fast = 1.111 must not appear at vol_ratio position (index 22)
    assert params[22] != pytest.approx(
        1.111
    ), "momentum_z_fast sentinel leaked into vol_ratio position"
    # atr_z = 14.14 must not appear at momentum_z_fast position ($9 = index 8)
    assert params[8] != pytest.approx(14.14), "atr_z sentinel leaked into momentum_z_fast position"


def test_body_ratio_at_index_70():
    """params[70] ($71) must be body_ratio sentinel value 55.01 -- first of the
    91 Renaissance primitive columns wired 2026-07-08."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert params[70] == pytest.approx(55.01), f"$71 (body_ratio) wrong: {params[70]}"


def test_hour_of_day_sin_at_index_88():
    """params[88] ($89) must be hour_of_day_sin sentinel value 56.01."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert params[88] == pytest.approx(56.01), f"$89 (hour_of_day_sin) wrong: {params[88]}"


def test_parkinson_vol_z_at_index_143():
    """params[143] ($144) must be parkinson_vol_z sentinel value 59.01.

    Index shifted from 145 (post migration 206) after migration 211 dropped
    new_high_flag/new_low_flag, both of which sit earlier in field order.
    """
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert params[143] == pytest.approx(59.01), f"$144 (parkinson_vol_z) wrong: {params[143]}"


def test_vol_skew_product_at_index_158():
    """params[158] ($159) must be vol_skew_product sentinel value 60.08 -- the
    last Renaissance primitive (canary + structural VP/SR columns follow it,
    migration 223/255). Index shifted from 160 after migration 211 dropped
    new_high_flag/new_low_flag.
    """
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert params[158] == pytest.approx(60.08), f"$159 (vol_skew_product) wrong: {params[158]}"


def test_sr_level_count_at_index_180_is_last_element():
    """params[180] ($181) must be sr_level_count sentinel value 61.17 -- the
    final column of the pre-Phase-164 contract, appended after the canary
    fields by migration 255 (Phase 163 Plan 01). No longer the true last
    element of the tuple as of migration 266 (Phase 164 Plan 01) -- 36 SMC
    institutional-footprint columns are appended after it; see
    test_gap_filled_at_index_257_is_last_element below for the current tail
    (migration 267, Phase 165 Plan 01)."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert len(params) == 258
    assert params[180] == pytest.approx(61.17), f"$181 (sr_level_count) wrong: {params[180]}"


def test_manip_strength_at_index_216_is_last_element():
    """params[216] ($217) must be manip_strength -- the final column of the
    pre-Phase-165 contract, appended after the structural VP/SR fields by
    migration 266's 36 SMC institutional-footprint columns (Phase 164 Plan
    01). No longer the true last element of the tuple as of migration 267
    (Phase 165 Plan 01) -- 41 swing/fib/trend/session structure columns are
    appended after it; see test_gap_filled_at_index_257_is_last_element below
    for the new tail. manip_strength is None here since
    _make_sentinel_record() does not set any of the 36 SMC fields
    (contract-only, placeholder None until Plans 02-04)."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert len(params) == 258
    assert params[216] is None, f"$217 (manip_strength) wrong: {params[216]}"


def test_gap_filled_at_index_257_is_last_element():
    """params[257] ($258) must be gap_filled -- the final column, appended
    after the SMC fields by migration 267's 41 swing/fib/trend/session
    structure columns (Phase 165 Plan 01). gap_filled is None here since
    _make_sentinel_record() does not set any of the 41 new Phase 165 fields
    (contract-only, placeholder None until Plans 02-04)."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert len(params) == 258
    assert params[257] is None, f"$258 (gap_filled) wrong: {params[257]}"
    assert params[257] == params[-1], "gap_filled must be the true last element"
