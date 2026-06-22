"""Regression test pinning the column mapping in _record_to_insert_params.

Verifies that the 61-element tuple produced by _record_to_insert_params
carries data in the correct position for each INSERT column:

  $1  (params[0])  -> feature_vector_id  UUID (content-key)
  $2  (params[1])  -> symbol             str
  $3  (params[2])  -> tf                 str
  $4  (params[3])  -> bar_ts             datetime
  $5  (params[4])  -> pipeline_version   str
  $6  (params[5])  -> regime             str | None
  $7  (params[6])  -> regime_label_source str
  $8  (params[7])  -> momentum_z_5       float
  $21 (params[20]) -> atr_z              float
  $30 (params[29]) -> hurst              float
  $55 (params[54]) -> ctf_momentum       float
  $61 (params[60]) -> ret_acf1_z         float

This test will fail if any column shift occurs in _record_to_insert_params.
"""

import uuid
from datetime import UTC, datetime


def _make_sentinel_record():
    """Build a FeatureVectorRecord with distinguishable sentinel values per field group."""
    from src.intelligence.schemas import FeatureVector, FeatureVectorRecord

    fv = FeatureVector(
        momentum_z_5=1.111,
        momentum_z_20=2.222,
        range_position=3.333,
        bar_close_pos=4.444,
        gap_z=5.555,
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
        ctf_momentum=48.48,
        ctf_vwap_align=49.49,
        ctf_regime_align=50.50,
        amihud_illiq_z=51.51,
        high_52w_dist=52.52,
        ret_skew_z=53.53,
        ret_acf1_z=54.54,
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


def test_params_length_is_61():
    """_record_to_insert_params must return exactly 61 elements."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert len(params) == 61, f"Expected 61, got {len(params)}"


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


def test_regime_at_index_5():
    """params[5] ($6) must be the regime string."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert params[5] == "trending_up", f"$6 must be 'trending_up', got {params[5]}"


def test_momentum_z_5_at_index_7():
    """params[7] ($8) must be momentum_z_5 sentinel value 1.111."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert params[7] == pytest.approx(1.111), f"$8 (momentum_z_5) wrong: {params[7]}"


def test_atr_z_at_index_20():
    """params[20] ($21) must be atr_z sentinel value 14.14."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert params[20] == pytest.approx(14.14), f"$21 (atr_z) wrong: {params[20]}"


def test_hurst_at_index_29():
    """params[29] ($30) must be hurst sentinel value 23.23."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert params[29] == pytest.approx(23.23), f"$30 (hurst) wrong: {params[29]}"


def test_ctf_momentum_at_index_54():
    """params[54] ($55) must be ctf_momentum sentinel value 48.48."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert params[54] == pytest.approx(48.48), f"$55 (ctf_momentum) wrong: {params[54]}"


def test_ret_acf1_z_at_index_60():
    """params[60] ($61) must be ret_acf1_z sentinel value 54.54."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert params[60] == pytest.approx(54.54), f"$61 (ret_acf1_z) wrong: {params[60]}"


def test_no_cross_contamination_between_feature_groups():
    """Verify momentum sentinel does not leak into vol_ratio position."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    # momentum_z_5 = 1.111 must not appear at vol_ratio position ($22 = index 21)
    assert params[21] != pytest.approx(
        1.111
    ), "momentum_z_5 sentinel leaked into vol_ratio position"
    # atr_z = 14.14 must not appear at momentum_z_5 position ($8 = index 7)
    assert params[7] != pytest.approx(14.14), "atr_z sentinel leaked into momentum_z_5 position"


import pytest
