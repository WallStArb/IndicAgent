"""Tests for feature_vector_writer — consumer group batch writer to feature_vectors hypertable."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_valid_feature_vector():
    """Build a valid FeatureVector for test fixtures."""
    from src.intelligence.schemas import FeatureVector

    return FeatureVector(
        momentum_z_fast=0.1,
        momentum_z_mid=0.2,
        range_position=0.5,
        bar_close_pos=0.6,
        gap_z=0.0,
        momentum_z_slow=0.0,
        momentum_reversal_z=0.0,
        informed_flow=0.0,
        volume_z=0.0,
        ofi_z=0.0,
        ofi_div=0.0,
        cvd_slope_z=0.0,
        cmf=0.0,
        rel_volume=1.0,
        vwap_dev_sigma=0.0,
        atr_z=0.5,
        vol_ratio=1.0,
        poc_dist_atr=0.1,
        va_position=0.5,
        sr_support_dist=2.0,
        sr_resist_dist=2.0,
        hmm_regime_prob=0.7,
        hmm_entropy=0.5,
        hmm_duration=5.0,
        hurst=0.55,
        shannon=1.2,
        garch_ratio=1.1,
        hma_slope_z=0.15,
        adx=25.0,
        aroon_fast=0.3,
        aroon_slow=0.2,
        rsi_fast=50.0,
        rsi_mid=50.0,
        rsi_slow=50.0,
        cci_fast=0.0,
        cci_mid=0.0,
        cci_slow=0.0,
        vix_z=0.0,
        flight_quality=0.0,
        yield_slope_z=0.0,
        in_ny_session=1.0,
        in_london_kz=0.0,
        in_overlap=0.0,
        power_hour=0.0,
        opening_range=0.0,
        above_wk_vwap=1.0,
        dow_sin=0.3,
        dow_cos=0.9,
        month_position=0.5,
        quarter_position=0.25,
        days_to_month_end=0.5,
        ctf_momentum=0.0,
        ctf_vwap_align=0.0,
        ctf_regime_align=0.0,
        amihud_illiq_z=0.0,
        high_52w_dist=0.05,
        ret_skew_z=0.0,
        ret_acf1_z=0.0,
        # Renaissance Primitives (Phase 142.5 Plan 01) — not yet in the persisted
        # tuple (migration 206 / writer wiring land in a later plan); construction
        # requires these non-optional fields.
        body_ratio=0.0,
        upper_wick_ratio=0.5,
        lower_wick_ratio=0.5,
        range_vs_atr=0.0,
        close_vs_open_direction=0.0,
        overnight_gap=0.0,
        overnight_gap_z=0.0,
        range_efficiency=0.0,
        ret_lag_1=0.0,
        ret_lag_2=0.0,
        ret_lag_3=0.0,
        ret_lag_fast=0.0,
        ret_lag_mid=0.0,
        ret_lag_slow=0.0,
        open_ret=0.0,
        intraday_ret=0.0,
        open_vs_intraday=0.0,
        session_time_pos=0.0,
        # Renaissance Primitives (Phase 142.5 Plan 02) — not yet in the persisted
        # tuple (migration 206 / writer wiring land in a later plan); construction
        # requires these non-optional fields.
        hour_of_day_sin=0.0,
        hour_of_day_cos=1.0,
        week_of_month_sin=0.0,
        week_of_month_cos=1.0,
        day_of_month_sin=0.0,
        day_of_month_cos=1.0,
        week_of_year_sin=0.0,
        week_of_year_cos=1.0,
        month_sin=0.0,
        month_cos=1.0,
        vol_acceleration=1.0,
        dollar_vol_z=0.0,
        vol_range_ratio=0.0,
        vol_trend_ratio=1.0,
        up_vol_ratio_fast=0.5,
        up_vol_ratio_slow=0.5,
        vol_percentile=0.5,
        vol_persistence=0.0,
        vol_std_z=0.0,
        mfi_fast=50.0,
        mfi_slow=50.0,
        obv_z=0.0,
        # Renaissance Primitives (Phase 142.5 Plan 05) — not yet in the persisted
        # tuple (migration 206 / writer wiring land in a later plan); construction
        # requires these non-optional fields.
        dist_from_high_fast=0.0,
        dist_from_high_slow=0.0,
        dist_from_low_fast=0.0,
        dist_from_low_slow=0.0,
        range_pct_fast=0.0,
        range_pct_slow=0.0,
        new_high_flag=0.0,
        new_low_flag=0.0,
        stoch_k_fast=0.5,
        stoch_k_slow=0.5,
        price_percentile_fast=0.5,
        price_percentile_slow=0.5,
        efficiency_ratio_fast=0.0,
        efficiency_ratio_slow=0.0,
        # Renaissance Primitives (Phase 142.5 Plan 03) — not yet in the persisted
        # tuple (migration 206 / writer wiring land in a later plan); construction
        # requires these non-optional fields.
        ret_kurtosis_z_fast=0.0,
        ret_kurtosis_z_slow=0.0,
        ret_autocorr_1=0.0,
        ret_autocorr_5=0.0,
        updown_ratio_fast=1.0,
        updown_ratio_slow=1.0,
        streak_z=0.0,
        realized_var_ratio_fast=1.0,
        realized_var_ratio_slow=1.0,
        range_to_close=0.0,
        true_range_pct=0.0,
        vol_of_vol=0.0,
        high_low_corr=0.0,
        variance_ratio_fast=1.0,
        variance_ratio_slow=1.0,
        vol_asymmetry_z=0.0,
        bb_pct_b_fast=0.5,
        bb_pct_b_slow=0.5,
        hv_z_fast=0.0,
        hv_z_slow=0.0,
        hv_ratio=1.0,
        # Renaissance Primitives (Phase 142.5 Plan 04) — not yet in the persisted
        # tuple (migration 206 / writer wiring land in a later plan); construction
        # requires these non-optional fields.
        parkinson_vol_z=0.0,
        garman_klass_vol_z=0.0,
        yang_zhang_vol_z=0.0,
        parkinson_vol_velocity=0.0,
        garman_klass_vol_velocity=0.0,
        yang_zhang_vol_velocity=0.0,
        vol_velocity_z=0.0,
        intraday_noise_ratio=1.0,
        # Renaissance Primitives (Phase 142.5 Plan 05.5) — not yet in the
        # persisted tuple (migration 206 / writer wiring land in a later
        # plan); construction requires these non-optional fields.
        vol_body_product=0.0,
        ret_vol_product_fast=0.0,
        price_vol_corr_fast=0.0,
        price_vol_corr_slow=0.0,
        range_vol_product=0.0,
        up_vol_body_diff=0.0,
        ret_vol_ratio_fast=0.0,
        vol_skew_product=0.0,
    )


def _make_valid_record():
    """Build a valid FeatureVectorRecord for test fixtures."""
    from src.intelligence.schemas import FeatureVectorRecord

    return FeatureVectorRecord(
        symbol="SPY",
        tf="5m",
        bar_ts=datetime(2026, 6, 20, 10, 0, 0, tzinfo=UTC),
        pipeline_version="3.0.0",
        feature_factory_version="1.0.0",
        regime="ranging",
        regime_label_source="filtered",
        vector=_make_valid_feature_vector(),
    )


def _make_valid_payload():
    """Build a valid dict payload (Kafka wire format) from a FeatureVectorRecord."""
    import dataclasses

    rec = _make_valid_record()
    return {
        "symbol": rec.symbol,
        "tf": rec.tf,
        "bar_ts": rec.bar_ts,
        "pipeline_version": rec.pipeline_version,
        "regime": rec.regime,
        "regime_label_source": rec.regime_label_source,
        "vector": dataclasses.asdict(rec.vector),
    }


# ── _record_to_insert_params ──────────────────────────────────────────────────


def test_record_to_insert_params_returns_161_tuple():
    """_record_to_insert_params returns exactly 161 elements matching INSERT columns
    (post migration 206, 2026-07-08 persistence-wiring fix)."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_valid_record()
    params = _record_to_insert_params(record)

    assert isinstance(params, tuple)
    assert len(params) == 161, f"Expected 161, got {len(params)}"


def test_record_to_insert_params_feature_vector_id_is_uuid():
    """$1 is a UUID (feature_vector_id content key)."""
    import uuid

    from services.feature_vector_writer import _record_to_insert_params

    record = _make_valid_record()
    params = _record_to_insert_params(record)

    assert isinstance(params[0], uuid.UUID), f"Expected UUID at [0], got {type(params[0])}"


def test_record_to_insert_params_structural_columns():
    """Params $2-$7 are the structural columns in correct order."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_valid_record()
    params = _record_to_insert_params(record)

    assert params[1] == "SPY"  # $2 symbol
    assert params[2] == "5m"  # $3 tf
    assert isinstance(params[3], datetime)  # $4 bar_ts
    assert params[4] == "3.0.0"  # $5 pipeline_version
    assert params[5] == "1.0.0"  # $6 feature_factory_version (NEW in 138-P1)
    assert params[6] == "ranging"  # $7 regime
    assert params[7] == "filtered"  # $8 regime_label_source


def test_record_to_insert_params_regime_can_be_none():
    """regime field is nullable — None passes through as None."""
    from services.feature_vector_writer import _record_to_insert_params
    from src.intelligence.schemas import FeatureVectorRecord

    rec = _make_valid_record()
    rec_no_regime = FeatureVectorRecord(
        symbol=rec.symbol,
        tf=rec.tf,
        bar_ts=rec.bar_ts,
        pipeline_version=rec.pipeline_version,
        feature_factory_version=rec.feature_factory_version,
        regime=None,
        regime_label_source=rec.regime_label_source,
        vector=rec.vector,
    )
    params = _record_to_insert_params(rec_no_regime)
    assert params[6] is None, "regime should be None at index 6"


def test_record_to_insert_params_feature_values_match_vector():
    """Feature float params ($8-$61) match FeatureVector fields in order."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_valid_record()
    params = _record_to_insert_params(record)
    v = record.vector

    # $9 = momentum_z_fast (index 8; shifted +1 by feature_factory_version at $6)
    assert params[8] == v.momentum_z_fast
    # $22 = atr_z (index 21)
    assert params[21] == v.atr_z
    # $31 = hurst (index 30)
    assert params[30] == v.hurst
    # $58 = ctf_regime_align (index 57)
    assert params[57] == v.ctf_regime_align
    # $62 = ret_acf1_z (index 61)
    assert params[61] == v.ret_acf1_z


def test_feature_vector_id_is_deterministic():
    """Same inputs always produce the same feature_vector_id (content-addressed)."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_valid_record()
    params1 = _record_to_insert_params(record)
    params2 = _record_to_insert_params(record)

    assert params1[0] == params2[0], "feature_vector_id must be deterministic"


def test_feature_vector_id_differs_for_different_inputs():
    """Different (symbol, tf, bar_ts) produce different feature_vector_ids."""
    import dataclasses

    from services.feature_vector_writer import _record_to_insert_params

    rec1 = _make_valid_record()
    rec2 = dataclasses.replace(rec1, symbol="TLT")
    params1 = _record_to_insert_params(rec1)
    params2 = _record_to_insert_params(rec2)

    assert params1[0] != params2[0], "Different symbols must produce different feature_vector_ids"


# ── _parse_payload ────────────────────────────────────────────────────────────


def test_parse_payload_valid_record_returns_161_param_tuple():
    """Valid FeatureVectorRecord payload parses to a 161-element params tuple
    (post migration 206, 2026-07-08 persistence-wiring fix)."""
    from services.feature_vector_writer import FeatureVectorWriter

    svc = FeatureVectorWriter.__new__(FeatureVectorWriter)
    svc.logger = MagicMock()
    svc._parse_errors_total = MagicMock()
    svc._rows_parsed_by_symbol_tf = MagicMock()

    payload = _make_valid_payload()
    valid, invalid = svc._parse_payload(payload)

    assert valid, "Expected non-empty valid list"
    assert not invalid
    assert len(valid) == 1
    assert isinstance(valid[0], tuple)
    assert len(valid[0]) == 161, f"Expected 161-element tuple, got {len(valid[0])}"


def test_parse_payload_malformed_returns_empty_valid_invalid_payload():
    """Malformed payload returns ([], [payload]) and increments parse errors."""
    from services.feature_vector_writer import FeatureVectorWriter

    svc = FeatureVectorWriter.__new__(FeatureVectorWriter)
    svc.logger = MagicMock()
    svc._parse_errors_total = MagicMock()
    svc._rows_parsed_by_symbol_tf = MagicMock()

    bad_payload = {"symbol": "SPY", "tf": "5m"}  # missing required fields
    valid, invalid = svc._parse_payload(bad_payload)

    assert not valid
    assert invalid == [bad_payload]
    svc._parse_errors_total.add.assert_called_once()


def test_parse_payload_non_dict_returns_empty():
    """Non-dict payload returns ([], [payload]) without crashing."""
    from services.feature_vector_writer import FeatureVectorWriter

    svc = FeatureVectorWriter.__new__(FeatureVectorWriter)
    svc.logger = MagicMock()
    svc._parse_errors_total = MagicMock()
    svc._rows_parsed_by_symbol_tf = MagicMock()

    valid, invalid = svc._parse_payload(b"not-json")
    assert not valid
    assert invalid


def test_parse_payload_missing_vector_returns_error():
    """Payload with non-dict 'vector' field returns parse error."""
    from services.feature_vector_writer import FeatureVectorWriter

    svc = FeatureVectorWriter.__new__(FeatureVectorWriter)
    svc.logger = MagicMock()
    svc._parse_errors_total = MagicMock()
    svc._rows_parsed_by_symbol_tf = MagicMock()

    payload = _make_valid_payload()
    payload["vector"] = "not-a-dict"
    valid, invalid = svc._parse_payload(payload)

    assert not valid
    assert invalid
    svc._parse_errors_total.add.assert_called_once()


# ── Consumer group and topic ──────────────────────────────────────────────────


def test_consumer_group_is_feature_vector_writer_group():
    """CONSUMER_GROUP must be 'feature_vector_writer_group' (T1: avoids offset collision)."""
    from services.feature_vector_writer import CONSUMER_GROUP

    assert CONSUMER_GROUP == "feature_vector_writer_group"


def test_topics_consumed_returns_feature_vectors_topic():
    """topics_consumed must return a list containing topic_feature_vectors."""
    from services.feature_vector_writer import FeatureVectorWriter

    svc = FeatureVectorWriter.__new__(FeatureVectorWriter)
    svc.settings = MagicMock(env_name="development")
    topics = svc.topics_consumed

    assert isinstance(topics, list)
    assert len(topics) > 0
    assert any("feature_vectors" in t for t in topics), f"Got: {topics}"


def test_topics_produced_is_empty():
    """topics_produced must be empty — DB writer has no Kafka output."""
    from services.feature_vector_writer import FeatureVectorWriter

    svc = FeatureVectorWriter.__new__(FeatureVectorWriter)
    assert svc.topics_produced == []


# ── No old references ─────────────────────────────────────────────────────────


def test_no_intelligence_features_reference():
    """feature_vector_writer must not reference intelligence_features."""
    import inspect

    from services import feature_vector_writer

    src = inspect.getsource(feature_vector_writer)
    assert "intelligence_features" not in src
    assert "BarIntelligenceRecord" not in src


def test_no_cross_asset_or_expiry_code():
    """Removed code paths must not exist in the module."""
    from services import feature_vector_writer

    assert not hasattr(
        feature_vector_writer, "_build_expiry_map"
    ), "_build_expiry_map must be removed"
    assert not hasattr(
        feature_vector_writer, "_compute_days_to_expiry"
    ), "_compute_days_to_expiry must be removed"
    assert not hasattr(
        feature_vector_writer.FeatureVectorWriter, "_process_cross_asset_message"
    ), "_process_cross_asset_message must be removed"


def test_no_hardcoded_dsn():
    """No hardcoded postgres:postgres@localhost DSN in feature_vector_writer."""
    import inspect

    from services import feature_vector_writer

    src = inspect.getsource(feature_vector_writer)
    assert "postgres:postgres@localhost" not in src


def test_no_load_config_method():
    """_load_config method must not exist (replaced by APR)."""
    from services import feature_vector_writer

    assert not hasattr(
        feature_vector_writer.FeatureVectorWriter, "_load_config"
    ), "_load_config must be removed"


def test_no_consumer_name_constant():
    """CONSUMER_NAME dead code must be removed."""
    from services import feature_vector_writer

    assert not hasattr(feature_vector_writer, "CONSUMER_NAME"), "CONSUMER_NAME must be removed"


def test_insert_sql_targets_feature_vectors():
    """_INSERT_FEATURE_VECTOR_SQL must target feature_vectors, not intelligence_features."""
    from services.feature_vector_writer import _INSERT_FEATURE_VECTOR_SQL

    assert "INSERT INTO feature_vectors" in _INSERT_FEATURE_VECTOR_SQL
    assert "intelligence_features" not in _INSERT_FEATURE_VECTOR_SQL
    assert "ON CONFLICT (symbol, tf, bar_ts) DO NOTHING" in _INSERT_FEATURE_VECTOR_SQL


def test_insert_sql_has_161_placeholders():
    """_INSERT_FEATURE_VECTOR_SQL must have exactly 161 positional placeholders $1..$161
    (post migration 206, 2026-07-08 persistence-wiring fix)."""
    import re

    from services.feature_vector_writer import _INSERT_FEATURE_VECTOR_SQL

    placeholders = re.findall(r"\$\d+", _INSERT_FEATURE_VECTOR_SQL)
    assert len(placeholders) == 161, f"Expected 161 placeholders, got {len(placeholders)}"


def test_insert_sql_includes_feature_vector_id_column():
    """_INSERT_FEATURE_VECTOR_SQL must include feature_vector_id as first column."""
    from services.feature_vector_writer import _INSERT_FEATURE_VECTOR_SQL

    assert "feature_vector_id" in _INSERT_FEATURE_VECTOR_SQL


# ── _flush_batch ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_flush_batch_calls_execute_batch_with_feature_vectors_sql():
    """_flush_batch calls execute_batch with _INSERT_FEATURE_VECTOR_SQL."""
    from services.feature_vector_writer import (
        _INSERT_FEATURE_VECTOR_SQL,
        FeatureVectorWriter,
        _record_to_insert_params,
    )

    svc = FeatureVectorWriter.__new__(FeatureVectorWriter)
    svc.logger = MagicMock()
    svc.batch_writes_total = MagicMock()
    svc.events_buffered_gauge = MagicMock()
    svc._total_batches = 0
    svc._batch_latency_attrs = {"agent_id": "feature_vector_writer"}
    svc.tracer = MagicMock()

    mock_db = MagicMock()
    mock_db.execute_batch = AsyncMock()
    svc.db_manager = mock_db

    record = _make_valid_record()
    params = _record_to_insert_params(record)
    batch = [params, params]

    await svc._flush_batch(batch)

    mock_db.execute_batch.assert_called_once()
    call_args = mock_db.execute_batch.call_args
    assert call_args[0][0] == _INSERT_FEATURE_VECTOR_SQL
    assert len(call_args[0][1]) == 2


# ── Lifecycle contract ────────────────────────────────────────────────────────


def test_feature_vector_writer_inherits_base_writer():
    """FeatureVectorWriter must inherit from BaseWriter (and BaseDaemon)."""
    from services.feature_vector_writer import FeatureVectorWriter
    from src.core.agent.base import BaseDaemon
    from src.core.agent.base_writer import BaseWriter

    assert issubclass(FeatureVectorWriter, BaseWriter)
    assert issubclass(FeatureVectorWriter, BaseDaemon)


def test_lag_threshold_messages_is_positive_int():
    """lag_threshold_messages must return a positive integer."""
    from services.feature_vector_writer import FeatureVectorWriter

    svc = FeatureVectorWriter.__new__(FeatureVectorWriter)
    assert isinstance(svc.lag_threshold_messages, int)
    assert svc.lag_threshold_messages > 0


def test_no_signal_signal_calls():
    """No sync signal.signal() calls must remain in the service file."""
    import inspect

    from services.feature_vector_writer import FeatureVectorWriter

    source = inspect.getsource(FeatureVectorWriter)
    assert "signal.signal(" not in source, "signal.signal() must not appear"


# ── DB connection safety ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_database_raises_on_db_failure():
    """_connect_database() must RAISE when DB initialization fails (ghost-run prevention)."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from services.feature_vector_writer import FeatureVectorWriter

    agent = FeatureVectorWriter.__new__(FeatureVectorWriter)
    agent.logger = MagicMock()
    agent.settings = MagicMock(database_url="postgresql://localhost:5432/test")
    agent.db_manager = None
    agent._db_connected = MagicMock()

    with patch("services.feature_vector_writer.DatabaseManager") as mock_db_cls:
        mock_db_instance = AsyncMock()
        mock_db_instance.initialize = AsyncMock(side_effect=Exception("Connection refused"))
        mock_db_cls.return_value = mock_db_instance

        with pytest.raises(Exception, match="Connection refused"):
            await agent._connect_database()

    assert agent.db_manager is None


@pytest.mark.asyncio
async def test_connect_database_no_ghost_run_path():
    """_connect_database() must not contain self.db_manager = None ghost-run pattern."""
    import inspect

    from services.feature_vector_writer import FeatureVectorWriter

    source = inspect.getsource(FeatureVectorWriter._connect_database)
    assert "self.db_manager = None" not in source
