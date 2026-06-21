"""Tests for feature_writer — consumer group batch writer to feature_vectors hypertable.

Phase 137 P4: Retargeted to feature_vectors via FeatureVectorRecord.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_valid_feature_vector():
    """Build a valid FeatureVector for test fixtures."""
    from src.intelligence.schemas import FeatureVector

    return FeatureVector(
        momentum_z_5=0.1,
        momentum_z_20=0.2,
        range_position=0.5,
        bar_close_pos=0.6,
        gap_z=0.0,
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
        ctf_momentum=0.0,
        ctf_vwap_align=0.0,
        ctf_regime_align=0.0,
        amihud_illiq_z=0.0,
        high_52w_dist=0.05,
        ret_skew_z=0.0,
        ret_acf1_z=0.0,
    )


def _make_valid_record():
    """Build a valid FeatureVectorRecord for test fixtures."""
    from src.intelligence.schemas import FeatureVectorRecord

    return FeatureVectorRecord(
        symbol="SPY",
        tf="5m",
        bar_ts=datetime(2026, 6, 20, 10, 0, 0, tzinfo=UTC),
        pipeline_version="3.0.0",
        regime="ranging",
        regime_label_source="filtered",
        vector=_make_valid_feature_vector(),
    )


def _make_valid_payload():
    """Build a valid dict payload (Kafka wire format) from a FeatureVectorRecord."""
    import dataclasses

    rec = _make_valid_record()
    # Simulate how the pipeline would serialize: dict with nested vector dict
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


def test_record_to_insert_params_returns_60_tuple():
    """_record_to_insert_params returns exactly 60 elements matching INSERT columns."""
    from services.feature_writer import _record_to_insert_params

    record = _make_valid_record()
    params = _record_to_insert_params(record)

    assert isinstance(params, tuple)
    assert len(params) == 60, f"Expected 60, got {len(params)}"


def test_record_to_insert_params_structural_columns():
    """First 6 params are the structural columns in correct order."""
    from services.feature_writer import _record_to_insert_params

    record = _make_valid_record()
    params = _record_to_insert_params(record)

    assert params[0] == "SPY"  # $1 symbol
    assert params[1] == "5m"  # $2 tf
    assert isinstance(params[2], datetime)  # $3 bar_ts
    assert params[3] == "3.0.0"  # $4 pipeline_version
    assert params[4] == "ranging"  # $5 regime
    assert params[5] == "filtered"  # $6 regime_label_source


def test_record_to_insert_params_regime_can_be_none():
    """regime field is nullable — None passes through as None."""
    from services.feature_writer import _record_to_insert_params
    from src.intelligence.schemas import FeatureVectorRecord

    rec = _make_valid_record()
    # FeatureVectorRecord is frozen — build a new one with regime=None
    rec_no_regime = FeatureVectorRecord(
        symbol=rec.symbol,
        tf=rec.tf,
        bar_ts=rec.bar_ts,
        pipeline_version=rec.pipeline_version,
        regime=None,
        regime_label_source=rec.regime_label_source,
        vector=rec.vector,
    )
    params = _record_to_insert_params(rec_no_regime)
    assert params[4] is None, "regime should be None"


def test_record_to_insert_params_feature_values_match_vector():
    """Feature float params ($7-$60) match the FeatureVector fields in order."""
    from services.feature_writer import _record_to_insert_params

    record = _make_valid_record()
    params = _record_to_insert_params(record)
    v = record.vector

    # $7 = momentum_z_5 (index 6)
    assert params[6] == v.momentum_z_5
    # $20 = atr_z (index 19)
    assert params[19] == v.atr_z
    # $29 = hurst (index 28)
    assert params[28] == v.hurst
    # $56 = ctf_regime_align (index 55)
    assert params[55] == v.ctf_regime_align
    # $60 = ret_acf1_z (index 59)
    assert params[59] == v.ret_acf1_z


# ── _parse_payload ────────────────────────────────────────────────────────────


def test_parse_payload_valid_record_returns_60_param_tuple():
    """Valid FeatureVectorRecord payload parses to a 42-element params tuple."""
    from services.feature_writer import FeatureWriter

    svc = FeatureWriter.__new__(FeatureWriter)
    svc.logger = MagicMock()
    svc._parse_errors_total = MagicMock()

    payload = _make_valid_payload()
    valid, invalid = svc._parse_payload(payload)

    assert valid, "Expected non-empty valid list"
    assert not invalid
    assert len(valid) == 1
    assert isinstance(valid[0], tuple)
    assert len(valid[0]) == 60, f"Expected 60-element tuple, got {len(valid[0])}"


def test_parse_payload_malformed_returns_empty_valid_invalid_payload():
    """Malformed payload returns ([], [payload]) and increments parse errors."""
    from services.feature_writer import FeatureWriter

    svc = FeatureWriter.__new__(FeatureWriter)
    svc.logger = MagicMock()
    svc._parse_errors_total = MagicMock()

    bad_payload = {"symbol": "SPY", "tf": "5m"}  # missing required fields
    valid, invalid = svc._parse_payload(bad_payload)

    assert not valid
    assert invalid == [bad_payload]
    svc._parse_errors_total.add.assert_called_once()


def test_parse_payload_non_dict_returns_empty():
    """Non-dict payload returns ([], [payload]) without crashing."""
    from services.feature_writer import FeatureWriter

    svc = FeatureWriter.__new__(FeatureWriter)
    svc.logger = MagicMock()
    svc._parse_errors_total = MagicMock()

    valid, invalid = svc._parse_payload(b"not-json")
    assert not valid
    assert invalid


def test_parse_payload_missing_vector_returns_error():
    """Payload with non-dict 'vector' field returns parse error."""
    from services.feature_writer import FeatureWriter

    svc = FeatureWriter.__new__(FeatureWriter)
    svc.logger = MagicMock()
    svc._parse_errors_total = MagicMock()

    payload = _make_valid_payload()
    payload["vector"] = "not-a-dict"
    valid, invalid = svc._parse_payload(payload)

    assert not valid
    assert invalid
    svc._parse_errors_total.add.assert_called_once()


# ── Consumer group and topic ──────────────────────────────────────────────────


def test_consumer_group_is_feature_vector_writer_group():
    """CONSUMER_GROUP must be 'feature_vector_writer_group' (T1: avoids offset collision)."""
    from services.feature_writer import CONSUMER_GROUP

    assert CONSUMER_GROUP == "feature_vector_writer_group"


def test_topics_consumed_returns_feature_vectors_topic():
    """topics_consumed must return a list containing topic_feature_vectors."""
    from services.feature_writer import FeatureWriter

    svc = FeatureWriter.__new__(FeatureWriter)
    svc.settings = MagicMock(env_name="development")
    topics = svc.topics_consumed

    assert isinstance(topics, list)
    assert len(topics) > 0
    assert any("feature_vectors" in t for t in topics), f"Got: {topics}"


def test_topics_produced_is_empty():
    """topics_produced must be empty — DB writer has no Kafka output."""
    from services.feature_writer import FeatureWriter

    svc = FeatureWriter.__new__(FeatureWriter)
    assert svc.topics_produced == []


# ── No old references ─────────────────────────────────────────────────────────


def test_no_intelligence_features_reference():
    """feature_writer must not reference intelligence_features."""
    import inspect

    from services import feature_writer

    src = inspect.getsource(feature_writer)
    assert "intelligence_features" not in src
    assert "BarIntelligenceRecord" not in src


def test_no_cross_asset_or_expiry_code():
    """Removed code paths must not exist in the module."""
    from services import feature_writer

    assert not hasattr(feature_writer, "_build_expiry_map"), "_build_expiry_map must be removed"
    assert not hasattr(
        feature_writer, "_compute_days_to_expiry"
    ), "_compute_days_to_expiry must be removed"
    assert not hasattr(
        feature_writer.FeatureWriter, "_process_cross_asset_message"
    ), "_process_cross_asset_message must be removed"


def test_insert_sql_targets_feature_vectors():
    """_INSERT_FEATURE_VECTOR_SQL must target feature_vectors, not intelligence_features."""
    from services.feature_writer import _INSERT_FEATURE_VECTOR_SQL

    assert "INSERT INTO feature_vectors" in _INSERT_FEATURE_VECTOR_SQL
    assert "intelligence_features" not in _INSERT_FEATURE_VECTOR_SQL
    assert "ON CONFLICT (symbol, tf, bar_ts) DO NOTHING" in _INSERT_FEATURE_VECTOR_SQL


def test_insert_sql_has_60_placeholders():
    """_INSERT_FEATURE_VECTOR_SQL must have exactly 60 positional placeholders $1..$60."""
    import re

    from services.feature_writer import _INSERT_FEATURE_VECTOR_SQL

    placeholders = re.findall(r"\$\d+", _INSERT_FEATURE_VECTOR_SQL)
    assert len(placeholders) == 60, f"Expected 60 placeholders, got {len(placeholders)}"


# ── _flush_batch ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_flush_batch_calls_execute_batch_with_feature_vectors_sql():
    """_flush_batch calls execute_batch with _INSERT_FEATURE_VECTOR_SQL."""
    from services.feature_writer import (
        _INSERT_FEATURE_VECTOR_SQL,
        FeatureWriter,
        _record_to_insert_params,
    )

    svc = FeatureWriter.__new__(FeatureWriter)
    svc.logger = MagicMock()
    svc.batch_writes_total = MagicMock()
    svc.events_buffered_gauge = MagicMock()
    svc._total_batches = 0
    svc._batch_latency_attrs = {"agent_id": "feature_writer"}
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


def test_feature_writer_inherits_base_writer():
    """FeatureWriter must inherit from BaseWriter (and BaseDaemon)."""
    from services.feature_writer import FeatureWriter
    from src.core.agent.base import BaseDaemon
    from src.core.agent.base_writer import BaseWriter

    assert issubclass(FeatureWriter, BaseWriter)
    assert issubclass(FeatureWriter, BaseDaemon)


def test_lag_threshold_messages_is_positive_int():
    """lag_threshold_messages must return a positive integer."""
    from services.feature_writer import FeatureWriter

    svc = FeatureWriter.__new__(FeatureWriter)
    assert isinstance(svc.lag_threshold_messages, int)
    assert svc.lag_threshold_messages > 0


def test_no_signal_signal_calls():
    """No sync signal.signal() calls must remain in the service file."""
    import inspect

    from services.feature_writer import FeatureWriter

    source = inspect.getsource(FeatureWriter)
    assert "signal.signal(" not in source, "signal.signal() must not appear"


# ── DB connection safety ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_database_raises_on_db_failure():
    """_connect_database() must RAISE when DB initialization fails (ghost-run prevention)."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from services.feature_writer import FeatureWriter

    agent = FeatureWriter.__new__(FeatureWriter)
    agent.logger = MagicMock()
    agent.config = {
        "database": {"dsn": "postgresql://localhost:5432/test"},
    }
    agent.db_manager = None
    agent._db_connected = MagicMock()

    with patch("services.feature_writer.DatabaseManager") as mock_db_cls:
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

    from services.feature_writer import FeatureWriter

    source = inspect.getsource(FeatureWriter._connect_database)
    assert "self.db_manager = None" not in source
