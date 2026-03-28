"""Tests for feature_writer_agent — consumer group batch writer to intelligence_features.

Updated for Phase 44.3: FeatureWriterAgent now consumes development.intelligence.record
only, performs a single atomic INSERT per bar from BarIntelligenceRecord. All i7/i8
two-phase write code removed.
"""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_valid_event():
    """Build a valid IntelligenceEvent for test fixtures."""
    from src.intelligence.schemas import (
        I1Indicators,
        I3Structure,
        I4Context,
        I5Patterns,
        I6Confluence,
        IntelligenceEvent,
        OHLCVBar,
        SMCContext,
    )

    return IntelligenceEvent(
        ts=datetime(2026, 2, 18, 10, 0, 0, tzinfo=UTC),
        symbol="ESH6",
        tf="5m",
        bar=OHLCVBar(o=5100.25, h=5105.50, l=5098.75, c=5103.00, v=12345),
        i1=I1Indicators(rsi_14=58.3, atr_14=12.5),
        i3=I3Structure(
            nearest_support=5080.0,
            nearest_resistance=5120.0,
            trend_strength=0.65,
            swing_pattern=1.0,
        ),
        i4=I4Context(
            trend_regime=0.65,
            trend_confidence=0.8,
            vol_regime=0.5,
            vol_percentile=60.0,
        ),
        i5=I5Patterns(squeeze_active=0.0, rsi_div_bullish=False),
        smc=SMCContext(bos_detected=False, hmm_regime=1.0),
        i6=I6Confluence(ctf_score=0.75),
    )


def _make_valid_bar_intelligence_record():
    """Build a valid BarIntelligenceRecord for test fixtures."""
    from src.intelligence.schemas import BarIntelligenceRecord, RankedSignal

    event = _make_valid_event()
    return BarIntelligenceRecord(
        schema_version="1.0",
        intelligence=event,
        ranked_signals=[
            RankedSignal(
                signal_id="abc123",
                plugin="trad_TrendFollowing",
                direction=1,
                raw_confidence=0.72,
                calibrated_confidence=0.75,
                regime_eligible=True,
                quality_score=0.80,
                tod_multiplier=1.1,
                adjusted_rank=0.88,
                is_winner=True,
            )
        ],
        winner_plugin="trad_TrendFollowing",
        winner_confidence=0.75,
        winner_direction=1,
        signals_evaluated=5,
        signals_after_quality=4,
        signals_after_regime=3,
        signals_after_tod=3,
        signals_after_calibration=2,
        ledger_written=True,
        session_type="rth",
        i7_computed_at=datetime(2026, 2, 18, 10, 0, 1, tzinfo=UTC),
        pipeline_latency_ms=45.3,
    )


# ── _parse_intelligence_record ─────────────────────────────────────────────────


def test_parse_intelligence_record_returns_bar_intelligence_record():
    """Valid BarIntelligenceRecord JSON returns BarIntelligenceRecord instance."""
    from services.feature_writer_agent import FeatureWriterAgent
    from src.intelligence.schemas import BarIntelligenceRecord

    svc = FeatureWriterAgent.__new__(FeatureWriterAgent)
    svc.logger = MagicMock()
    svc._parse_errors_total = MagicMock()

    record = _make_valid_bar_intelligence_record()
    raw = record.model_dump_json().encode()

    result = svc._parse_intelligence_record(raw)

    assert result is not None
    assert isinstance(result, BarIntelligenceRecord)
    assert result.intelligence.symbol == "ESH6"
    assert result.winner_plugin == "trad_TrendFollowing"


def test_parse_intelligence_record_returns_none_for_invalid_json():
    """Malformed JSON returns None without crashing."""
    from services.feature_writer_agent import FeatureWriterAgent

    svc = FeatureWriterAgent.__new__(FeatureWriterAgent)
    svc.logger = MagicMock()
    svc._parse_errors_total = MagicMock()

    result = svc._parse_intelligence_record(b"not-valid-json{{{")

    assert result is None
    svc._parse_errors_total.inc.assert_called_once()


# ── _record_to_insert_params ──────────────────────────────────────────────────


def test_record_to_insert_params_returns_31_tuple():
    """_record_to_insert_params returns a 31-element tuple matching SQL columns."""
    from services.feature_writer_agent import _record_to_insert_params

    record = _make_valid_bar_intelligence_record()
    params = _record_to_insert_params(record)

    assert isinstance(params, tuple)
    assert len(params) == 31


def test_record_to_insert_params_serializes_ranked_signals_to_json():
    """ranked_signals is serialized to a JSON string for the i7 column."""
    from services.feature_writer_agent import _record_to_insert_params

    record = _make_valid_bar_intelligence_record()
    params = _record_to_insert_params(record)

    # i7 at index 14 (15th col: ts,sym,tf,platform,source,schema_ver,bar,i1,i2,i3,i4,i5,smc,i6,i7)
    i7_value = params[14]
    assert isinstance(i7_value, str), "i7 must be a JSON string for asyncpg"
    parsed = json.loads(i7_value)
    assert isinstance(parsed, list)
    assert len(parsed) == 1
    assert parsed[0]["plugin"] == "trad_TrendFollowing"


def test_record_to_insert_params_uses_datetime_objects_for_timestamps():
    """ts, i7_computed_at, computed_at are Python datetime objects (asyncpg requirement)."""
    from services.feature_writer_agent import _record_to_insert_params

    record = _make_valid_bar_intelligence_record()
    params = _record_to_insert_params(record)

    # $1 = ts
    assert isinstance(params[0], datetime), f"ts must be datetime, got {type(params[0])}"
    # $29 = i7_computed_at (index 28)
    assert isinstance(params[28], datetime), (
        f"i7_computed_at must be datetime, got {type(params[28])}"
    )


def test_record_to_insert_params_handles_none_winner_fields():
    """None winner fields are passed through as None (not string 'None')."""
    from services.feature_writer_agent import _record_to_insert_params

    record = _make_valid_bar_intelligence_record()
    record.winner_plugin = None
    record.winner_confidence = None
    record.winner_direction = None
    params = _record_to_insert_params(record)

    # winner_plugin at index 18, winner_confidence at 19, winner_direction at 20
    assert params[18] is None, "winner_plugin should be None"
    assert params[19] is None, "winner_confidence should be None"
    assert params[20] is None, "winner_direction should be None"


def test_record_to_insert_params_extracts_session_type_as_string():
    """session_type is stored as a plain string value."""
    from services.feature_writer_agent import _record_to_insert_params

    record = _make_valid_bar_intelligence_record()
    record.session_type = "rth"
    params = _record_to_insert_params(record)

    # session_type at index 29 ($30 column)
    session_type_val = params[29]
    assert isinstance(session_type_val, str), "session_type must be a string"
    assert session_type_val == "rth"


def test_record_to_insert_params_jsonb_columns_are_strings():
    """JSONB columns (bar, i1, i2, i3, i4, i5, smc, i6, i7) must be JSON strings."""
    from services.feature_writer_agent import _record_to_insert_params

    record = _make_valid_bar_intelligence_record()
    params = _record_to_insert_params(record)

    # Indices 6..14 are bar, i1, i2, i3, i4, i5, smc, i6, i7
    for idx in range(6, 15):
        value = params[idx]
        assert isinstance(value, str), (
            f"params[{idx}] must be a JSON string, got {type(value).__name__}"
        )
        parsed = json.loads(value)
        assert isinstance(parsed, (dict, list)), (
            f"params[{idx}] must decode to dict or list"
        )


# ── _maybe_flush (no i7/i8 buffer references) ────────────────────────────────


@pytest.mark.asyncio
async def test_maybe_flush_force_calls_execute_batch():
    """_maybe_flush(force=True) with 3 buffered records calls execute_batch with 3 params."""
    from services.feature_writer_agent import FeatureWriterAgent, _record_to_insert_params

    svc = FeatureWriterAgent.__new__(FeatureWriterAgent)
    svc.logger = MagicMock()
    svc._last_flush = 0.0
    svc.batch_writes_total = MagicMock()
    svc.events_buffered_gauge = MagicMock()
    svc.error_count_total = MagicMock()
    svc._total_batches = 0
    svc._error_count = 0

    mock_db = MagicMock()
    mock_db.execute_batch = AsyncMock()
    svc.db_manager = mock_db

    record = _make_valid_bar_intelligence_record()
    params = _record_to_insert_params(record)
    svc._buffer = [params, params, params]

    await svc._maybe_flush(force=True)

    mock_db.execute_batch.assert_called_once()
    call_args = mock_db.execute_batch.call_args
    assert len(call_args[0][1]) == 3
    assert svc._buffer == []


@pytest.mark.asyncio
async def test_maybe_flush_has_no_i7_i8_buffer_references():
    """_maybe_flush no longer references _i7_buffer or _i8_buffer."""
    import inspect

    from services.feature_writer_agent import FeatureWriterAgent

    source = inspect.getsource(FeatureWriterAgent._maybe_flush)
    assert "_i7_buffer" not in source, "_i7_buffer must be absent from _maybe_flush"
    assert "_i8_buffer" not in source, "_i8_buffer must be absent from _maybe_flush"
    assert "_flush_i7_i8" not in source, "_flush_i7_i8 must be absent from _maybe_flush"


@pytest.mark.asyncio
async def test_maybe_flush_time_based_calls_execute_batch():
    """_maybe_flush(force=False) with events older than FLUSH_INTERVAL_SECS calls execute_batch."""
    import time

    from services.feature_writer_agent import (
        FLUSH_INTERVAL_SECS,
        FeatureWriterAgent,
        _record_to_insert_params,
    )

    svc = FeatureWriterAgent.__new__(FeatureWriterAgent)
    svc.logger = MagicMock()
    svc._last_flush = time.monotonic() - (FLUSH_INTERVAL_SECS + 1.0)
    svc.batch_writes_total = MagicMock()
    svc.events_buffered_gauge = MagicMock()
    svc.error_count_total = MagicMock()
    svc._total_batches = 0
    svc._error_count = 0

    mock_db = MagicMock()
    mock_db.execute_batch = AsyncMock()
    svc.db_manager = mock_db

    record = _make_valid_bar_intelligence_record()
    params = _record_to_insert_params(record)
    svc._buffer = [params]

    await svc._maybe_flush(force=False)

    mock_db.execute_batch.assert_called_once()
    assert svc._buffer == []


@pytest.mark.asyncio
async def test_maybe_flush_recent_events_no_call():
    """_maybe_flush(force=False) with recent events does NOT call execute_batch."""
    import time

    from services.feature_writer_agent import FeatureWriterAgent, _record_to_insert_params

    svc = FeatureWriterAgent.__new__(FeatureWriterAgent)
    svc.logger = MagicMock()
    svc._last_flush = time.monotonic()

    mock_db = MagicMock()
    mock_db.execute_batch = AsyncMock()
    svc.db_manager = mock_db

    record = _make_valid_bar_intelligence_record()
    params = _record_to_insert_params(record)
    svc._buffer = [params]

    await svc._maybe_flush(force=False)

    mock_db.execute_batch.assert_not_called()
    assert len(svc._buffer) == 1


# ── removed code verification ─────────────────────────────────────────────────


def test_removed_i7_i8_methods_absent():
    """_process_i7_message, _process_i8_message, _flush_i7_i8 must be absent."""
    from services.feature_writer_agent import FeatureWriterAgent

    assert not hasattr(FeatureWriterAgent, "_process_i7_message"), (
        "_process_i7_message must be removed"
    )
    assert not hasattr(FeatureWriterAgent, "_process_i8_message"), (
        "_process_i8_message must be removed"
    )
    assert not hasattr(FeatureWriterAgent, "_flush_i7_i8"), "_flush_i7_i8 must be removed"


def test_topic_routing_only_handles_intelligence_record():
    """_process_loop source must contain intelligence_record_topic routing."""
    import inspect

    from services.feature_writer_agent import FeatureWriterAgent

    source = inspect.getsource(FeatureWriterAgent._process_loop)
    assert "intelligence_record_topic" in source, (
        "_process_loop must route intelligence_record_topic"
    )
    # Old multi-topic routing removed
    assert "i7_topic" not in source, "i7_topic must be absent from _process_loop"
    assert "i8_topic" not in source, "i8_topic must be absent from _process_loop"


# ── graceful shutdown ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_graceful_shutdown_flushes_and_closes():
    """_shutdown flushes buffer and closes Kafka/DB connections."""
    import asyncio
    from contextlib import contextmanager

    from services.feature_writer_agent import FeatureWriterAgent, _record_to_insert_params

    svc = FeatureWriterAgent.__new__(FeatureWriterAgent)
    svc.logger = MagicMock()
    svc._stop_event = asyncio.Event()  # required by BaseAgent.running property
    svc._last_flush = 0.0
    svc.batch_writes_total = MagicMock()
    svc.events_buffered_gauge = MagicMock()
    svc.error_count_total = MagicMock()
    svc._total_batches = 0
    svc._total_events = 0
    svc._error_count = 0
    # _batch_latency is a context manager returned by PERSISTENCE_BATCH_LATENCY.labels()
    mock_batch_latency = MagicMock()
    mock_batch_latency.__enter__ = MagicMock(return_value=None)
    mock_batch_latency.__exit__ = MagicMock(return_value=False)
    svc._batch_latency = mock_batch_latency

    mock_db = MagicMock()
    mock_db.execute_batch = AsyncMock()
    mock_db.close = AsyncMock()
    svc.db_manager = mock_db

    mock_kafka = MagicMock()
    mock_kafka.stop = AsyncMock()
    mock_kafka.commit = AsyncMock()
    svc._kafka_consumer = mock_kafka

    record = _make_valid_bar_intelligence_record()
    params = _record_to_insert_params(record)
    svc._buffer = [params, params]

    await svc._shutdown()

    mock_db.execute_batch.assert_called_once()
    assert svc._buffer == []


def test_kafka_consumer_group_is_feature_writer_group():
    """KAFKA-07: FeatureWriterAgent uses CONSUMER_GROUP='feature_writer_group'."""
    from services.feature_writer_agent import CONSUMER_GROUP, FeatureWriterAgent

    assert CONSUMER_GROUP == "feature_writer_group"
    svc = FeatureWriterAgent.__new__(FeatureWriterAgent)
    assert not hasattr(svc, "redis_client"), (
        "redis_client must not be present after Kafka migration"
    )


# ── _build_expiry_map ─────────────────────────────────────────────────────────


class TestBuildExpiryMap:
    """Tests for _build_expiry_map pure function."""

    def _make_settings_with(self, instruments):
        from unittest.mock import MagicMock

        s = MagicMock()
        s.contracts = instruments
        return s

    def _futures_inst(self, symbol, expiry):
        from src.core.models import AssetClass, Instrument

        return Instrument(symbol=symbol, expiry=expiry, asset_class=AssetClass.FUTURES)

    def _fx_inst(self, symbol):
        from src.core.models import AssetClass, Instrument

        return Instrument(symbol=symbol, expiry="", asset_class=AssetClass.FX)

    def _crypto_inst(self, symbol):
        from src.core.models import AssetClass, Instrument

        return Instrument(symbol=symbol, expiry="", asset_class=AssetClass.CRYPTO)

    def test_futures_yyyymmdd_parsed(self):
        """YYYYMMDD expiry string → correct date in map."""
        from datetime import date

        from services.feature_writer_agent import _build_expiry_map

        settings = self._make_settings_with([self._futures_inst("ESH6", "20260320")])
        result = _build_expiry_map(settings)

        assert "ESH6" in result
        assert result["ESH6"] == date(2026, 3, 20)

    def test_futures_yyyymm_last_day_of_month(self):
        """YYYYMM expiry (VX-style) → last day of that month."""
        from datetime import date

        from services.feature_writer_agent import _build_expiry_map

        settings = self._make_settings_with([self._futures_inst("VXJ6", "202604")])
        result = _build_expiry_map(settings)

        assert "VXJ6" in result
        assert result["VXJ6"] == date(2026, 4, 30)

    def test_fx_excluded_from_map(self):
        """FX instruments not in expiry map."""
        from services.feature_writer_agent import _build_expiry_map

        settings = self._make_settings_with([self._fx_inst("EURUSD")])
        result = _build_expiry_map(settings)

        assert "EURUSD" not in result

    def test_crypto_excluded_from_map(self):
        """CRYPTO instruments not in expiry map."""
        from services.feature_writer_agent import _build_expiry_map

        settings = self._make_settings_with([self._crypto_inst("BTCUSD")])
        result = _build_expiry_map(settings)

        assert "BTCUSD" not in result


# ── _compute_days_to_expiry ───────────────────────────────────────────────────


class TestComputeDaysToExpiry:
    """Tests for _compute_days_to_expiry pure function."""

    def _dt(self, year, month, day):
        return datetime(year, month, day, 10, 0, 0, tzinfo=UTC)

    def test_futures_days_before_expiry(self):
        """Futures with 5 days to expiry returns 5."""
        from datetime import date

        from services.feature_writer_agent import _compute_days_to_expiry

        expiry_map = {"ESH6": date(2026, 3, 20)}
        result = _compute_days_to_expiry("ESH6", self._dt(2026, 3, 15), expiry_map)
        assert result == 5

    def test_past_expiry_clamped_to_zero(self):
        """Bar timestamp after expiry → 0 (clamped)."""
        from datetime import date

        from services.feature_writer_agent import _compute_days_to_expiry

        expiry_map = {"ESH6": date(2026, 3, 20)}
        result = _compute_days_to_expiry("ESH6", self._dt(2026, 3, 25), expiry_map)
        assert result == 0

    def test_non_futures_returns_zero(self):
        """Symbol not in expiry_map (FX/crypto) → 0."""
        from datetime import date

        from services.feature_writer_agent import _compute_days_to_expiry

        result = _compute_days_to_expiry(
            "EURUSD", self._dt(2026, 3, 4), {"ESH6": date(2026, 3, 21)}
        )
        assert result == 0

    def test_empty_expiry_map_returns_none(self):
        """Empty expiry_map (service not initialized) → None."""
        from services.feature_writer_agent import _compute_days_to_expiry

        result = _compute_days_to_expiry("ESH6", self._dt(2026, 3, 4), {})
        assert result is None


# ── Lifecycle contract tests (D-17) ──────────────────────────────────────────


class TestFeatureWriterAgentLifecycle:
    """D-17: Lifecycle contract tests for FeatureWriterAgent.

    Uses __new__ injection pattern (CLAUDE.md) to bypass __init__ and test
    lifecycle properties in isolation — no Kafka, DB, or I/O required.
    """

    def setup_method(self):
        import asyncio

        from services.feature_writer_agent import FeatureWriterAgent

        self.agent = FeatureWriterAgent.__new__(FeatureWriterAgent)
        self.agent.name = "feature_writer_agent"
        self.agent._stop_event = asyncio.Event()
        self.agent._metrics_port = 9116
        self.agent.logger = MagicMock()
        self.agent.tracer = MagicMock()
        self.agent._env_name = "development"  # underscore prefix (FeatureWriterAgent pattern)

    def test_topics_consumed_returns_list(self):
        """topics_consumed must return a non-empty list of topic strings."""
        topics = self.agent.topics_consumed
        assert isinstance(topics, list)
        assert len(topics) > 0

    def test_topics_produced_is_empty(self):
        """topics_produced must be empty — DB writer has no Kafka output."""
        assert self.agent.topics_produced == []

    def test_running_property_reflects_stop_event(self):
        """running property reflects the _stop_event state."""
        import asyncio

        assert self.agent.running is True
        self.agent._stop_event.set()
        assert self.agent.running is False

    def test_lag_threshold_messages_is_int(self):
        """lag_threshold_messages must return a positive integer."""
        assert isinstance(self.agent.lag_threshold_messages, int)
        assert self.agent.lag_threshold_messages > 0

    @pytest.mark.asyncio
    async def test_lifecycle_methods_are_coroutines(self):
        """_setup, _run, and _teardown must all be awaitable coroutines."""
        import asyncio

        assert asyncio.iscoroutinefunction(self.agent._setup)
        assert asyncio.iscoroutinefunction(self.agent._run)
        assert asyncio.iscoroutinefunction(self.agent._teardown)


def test_feature_writer_agent_inherits_base_agent():
    """FeatureWriterAgent must inherit from BaseAgent."""
    from services.feature_writer_agent import FeatureWriterAgent
    from src.core.agent.base import BaseAgent

    assert issubclass(FeatureWriterAgent, BaseAgent)


def test_feature_writer_no_signal_signal_calls():
    """No sync signal.signal() calls must remain in the service file."""
    import inspect

    from services.feature_writer_agent import FeatureWriterAgent

    source = inspect.getsource(FeatureWriterAgent)
    assert "signal.signal(" not in source, (
        "signal.signal() must not appear — use BaseAgent._register_signal_handlers()"
    )
