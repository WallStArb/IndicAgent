"""Tests for feature_writer_service — consumer group batch writer to intelligence_features."""
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


def _make_valid_event_json() -> bytes:
    """Return bytes of a valid IntelligenceEvent JSON for stream message fields."""
    return _make_valid_event().model_dump_json().encode()


# ── _parse_intelligence_event ─────────────────────────────────────────────────

def test_parse_valid_event_returns_intelligence_event():
    """Valid IntelligenceEvent JSON in b'event' field returns IntelligenceEvent."""
    from services.feature_writer_service import _parse_intelligence_event
    from src.intelligence.schemas import IntelligenceEvent

    fields = {b"event": _make_valid_event_json()}
    result = _parse_intelligence_event(fields)

    assert result is not None
    assert isinstance(result, IntelligenceEvent)
    assert result.symbol == "ESH6"
    assert result.tf == "5m"
    assert result.bar.o == pytest.approx(5100.25)
    assert result.bar.v == 12345


def test_parse_missing_event_field_returns_none():
    """Empty fields dict (missing b'event' key) returns None without crashing."""
    from services.feature_writer_service import _parse_intelligence_event

    result = _parse_intelligence_event({})
    assert result is None


def test_parse_malformed_json_returns_none():
    """Garbled JSON bytes returns None (ack-and-skip, no crash)."""
    from services.feature_writer_service import _parse_intelligence_event

    result = _parse_intelligence_event({b"event": b"not-valid-json{{{"})
    assert result is None


# ── _event_to_insert_params ───────────────────────────────────────────────────

def test_event_to_insert_params_returns_17_tuple():
    """_event_to_insert_params returns 18-element tuple (14 base + 3 timing + 1 days_to_expiry)."""
    from services.feature_writer_service import _event_to_insert_params

    event = _make_valid_event()
    params = _event_to_insert_params(event)

    assert isinstance(params, tuple)
    assert len(params) == 18  # was 17; now includes days_to_expiry at $18


def test_event_to_insert_params_first_element_is_datetime():
    """First element of insert params is a datetime (ts column)."""
    from services.feature_writer_service import _event_to_insert_params

    event = _make_valid_event()
    params = _event_to_insert_params(event)

    assert isinstance(params[0], datetime)
    assert params[0].year == 2026


def test_event_to_insert_params_jsonb_columns_are_strings():
    """JSONB columns (elements 6..12) must be json.dumps() strings, not dicts.

    asyncpg does not auto-serialize dicts to JSONB — they must be strings.
    """
    from services.feature_writer_service import _event_to_insert_params

    event = _make_valid_event()
    params = _event_to_insert_params(event)

    # Elements at indices 6..12 are the 7 JSONB columns: bar, i1, i3, i4, i5, smc, i6
    for idx in range(6, 13):
        value = params[idx]
        assert isinstance(value, str), (
            f"params[{idx}] must be a JSON string, got {type(value).__name__}"
        )
        # Must be valid JSON
        parsed = json.loads(value)
        assert isinstance(parsed, dict), f"params[{idx}] must decode to a dict"


# ── FeatureWriterService._maybe_flush ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_maybe_flush_force_calls_execute_batch():
    """_maybe_flush(force=True) with 3 buffered events calls execute_batch with 3 params."""
    from services.feature_writer_service import FeatureWriterService

    svc = FeatureWriterService.__new__(FeatureWriterService)
    svc.logger = MagicMock()
    svc._last_flush = 0.0  # far in the past
    svc.batch_writes_total = MagicMock()
    svc.events_buffered_gauge = MagicMock()
    svc.error_count_total = MagicMock()
    svc._total_batches = 0
    svc._error_count = 0

    mock_db = MagicMock()
    mock_db.execute_batch = AsyncMock()
    svc.db_manager = mock_db

    event = _make_valid_event()
    from services.feature_writer_service import _event_to_insert_params
    params = _event_to_insert_params(event)
    svc._buffer = [params, params, params]

    await svc._maybe_flush(force=True)

    mock_db.execute_batch.assert_called_once()
    call_args = mock_db.execute_batch.call_args
    # Second argument is the params list
    assert len(call_args[0][1]) == 3
    assert svc._buffer == []


@pytest.mark.asyncio
async def test_maybe_flush_time_based_calls_execute_batch():
    """_maybe_flush(force=False) with events older than FLUSH_INTERVAL_SECS calls execute_batch."""
    import time

    from services.feature_writer_service import FLUSH_INTERVAL_SECS, FeatureWriterService

    svc = FeatureWriterService.__new__(FeatureWriterService)
    svc.logger = MagicMock()
    # Set last_flush far enough in the past to trigger time-based flush
    svc._last_flush = time.monotonic() - (FLUSH_INTERVAL_SECS + 1.0)
    svc.batch_writes_total = MagicMock()
    svc.events_buffered_gauge = MagicMock()
    svc.error_count_total = MagicMock()
    svc._total_batches = 0
    svc._error_count = 0

    mock_db = MagicMock()
    mock_db.execute_batch = AsyncMock()
    svc.db_manager = mock_db

    event = _make_valid_event()
    from services.feature_writer_service import _event_to_insert_params
    params = _event_to_insert_params(event)
    svc._buffer = [params]

    await svc._maybe_flush(force=False)

    mock_db.execute_batch.assert_called_once()
    assert svc._buffer == []


@pytest.mark.asyncio
async def test_maybe_flush_recent_events_no_call():
    """_maybe_flush(force=False) with recent events does NOT call execute_batch."""
    import time

    from services.feature_writer_service import FeatureWriterService

    svc = FeatureWriterService.__new__(FeatureWriterService)
    svc.logger = MagicMock()
    # Just flushed — last_flush is current time
    svc._last_flush = time.monotonic()

    mock_db = MagicMock()
    mock_db.execute_batch = AsyncMock()
    svc.db_manager = mock_db

    event = _make_valid_event()
    from services.feature_writer_service import _event_to_insert_params
    params = _event_to_insert_params(event)
    svc._buffer = [params]

    await svc._maybe_flush(force=False)

    mock_db.execute_batch.assert_not_called()
    # Buffer should still have the event
    assert len(svc._buffer) == 1


# ── graceful shutdown ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_graceful_shutdown_sets_flag_and_flushes():
    """_shutdown sets shutdown_requested=True and flushes buffer."""
    from services.feature_writer_service import FeatureWriterService

    svc = FeatureWriterService.__new__(FeatureWriterService)
    svc.logger = MagicMock()
    svc.shutdown_requested = False
    svc._last_flush = 0.0
    svc.running = True
    svc.batch_writes_total = MagicMock()
    svc.events_buffered_gauge = MagicMock()
    svc.error_count_total = MagicMock()
    svc._total_batches = 0
    svc._total_events = 0
    svc._error_count = 0

    mock_db = MagicMock()
    mock_db.execute_batch = AsyncMock()
    mock_db.close = AsyncMock()
    svc.db_manager = mock_db

    # Kafka migration: _kafka_consumer replaces redis_client
    mock_kafka = MagicMock()
    mock_kafka.stop = AsyncMock()
    svc._kafka_consumer = mock_kafka

    event = _make_valid_event()
    from services.feature_writer_service import _event_to_insert_params
    params = _event_to_insert_params(event)
    svc._buffer = [params, params]

    await svc._shutdown()

    assert svc.shutdown_requested is True
    # Buffer must be flushed on shutdown
    mock_db.execute_batch.assert_called_once()
    assert svc._buffer == []


def test_kafka_consumer_group_is_feature_writer_group():
    """KAFKA-07: FeatureWriterService uses CONSUMER_GROUP='feature_writer_group' (no xreadgroup)."""
    from services.feature_writer_service import CONSUMER_GROUP, FeatureWriterService

    assert CONSUMER_GROUP == "feature_writer_group"
    # Verify no redis_client attribute on new instance (Kafka-native)
    svc = FeatureWriterService.__new__(FeatureWriterService)
    assert not hasattr(svc, "redis_client"), "redis_client must not be present after Kafka migration"


# ── _build_expiry_map ─────────────────────────────────────────────────────────

class TestBuildExpiryMap:
    """Tests for _build_expiry_map pure function."""

    def _make_settings_with(self, instruments):
        """Build a minimal Settings-like object with given contracts list."""
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

        from services.feature_writer_service import _build_expiry_map

        settings = self._make_settings_with([self._futures_inst("ESH6", "20260320")])
        result = _build_expiry_map(settings)

        assert "ESH6" in result
        assert result["ESH6"] == date(2026, 3, 20)

    def test_futures_yyyymm_last_day_of_month(self):
        """YYYYMM expiry (VX-style) → last day of that month."""
        from datetime import date

        from services.feature_writer_service import _build_expiry_map

        settings = self._make_settings_with([self._futures_inst("VXJ6", "202604")])
        result = _build_expiry_map(settings)

        assert "VXJ6" in result
        assert result["VXJ6"] == date(2026, 4, 30)

    def test_fx_excluded_from_map(self):
        """FX instruments not in expiry map."""
        from services.feature_writer_service import _build_expiry_map

        settings = self._make_settings_with([self._fx_inst("EURUSD")])
        result = _build_expiry_map(settings)

        assert "EURUSD" not in result

    def test_crypto_excluded_from_map(self):
        """CRYPTO instruments not in expiry map."""
        from services.feature_writer_service import _build_expiry_map

        settings = self._make_settings_with([self._crypto_inst("BTCUSD")])
        result = _build_expiry_map(settings)

        assert "BTCUSD" not in result


# ── _compute_days_to_expiry ───────────────────────────────────────────────────

class TestComputeDaysToExpiry:
    """Tests for _compute_days_to_expiry pure function."""

    def _dt(self, year, month, day):
        from datetime import UTC, datetime
        return datetime(year, month, day, 10, 0, 0, tzinfo=UTC)

    def test_futures_days_before_expiry(self):
        """Futures with 5 days to expiry returns 5."""
        from datetime import date

        from services.feature_writer_service import _compute_days_to_expiry

        expiry_map = {"ESH6": date(2026, 3, 20)}
        result = _compute_days_to_expiry("ESH6", self._dt(2026, 3, 15), expiry_map)
        assert result == 5

    def test_past_expiry_clamped_to_zero(self):
        """Bar timestamp after expiry → 0 (clamped)."""
        from datetime import date

        from services.feature_writer_service import _compute_days_to_expiry

        expiry_map = {"ESH6": date(2026, 3, 20)}
        result = _compute_days_to_expiry("ESH6", self._dt(2026, 3, 25), expiry_map)
        assert result == 0

    def test_non_futures_returns_zero(self):
        """Symbol not in expiry_map (FX/crypto) → 0."""
        from datetime import date

        from services.feature_writer_service import _compute_days_to_expiry

        result = _compute_days_to_expiry(
            "EURUSD", self._dt(2026, 3, 4), {"ESH6": date(2026, 3, 21)}
        )
        assert result == 0

    def test_empty_expiry_map_returns_none(self):
        """Empty expiry_map (service not initialized) → None."""
        from services.feature_writer_service import _compute_days_to_expiry

        result = _compute_days_to_expiry("ESH6", self._dt(2026, 3, 4), {})
        assert result is None


# ── _event_to_insert_params with expiry_map ───────────────────────────────────

def test_event_to_insert_params_18_with_expiry_map():
    """_event_to_insert_params with expiry_map returns 18-tuple, $18 is int."""
    from datetime import date

    from services.feature_writer_service import _event_to_insert_params

    event = _make_valid_event()  # symbol="ESH6", ts=datetime(2026,2,18,10,0,0)
    expiry_map = {"ESH6": date(2026, 3, 20)}
    params = _event_to_insert_params(event, expiry_map)

    assert len(params) == 18
    assert isinstance(params[17], int)
    assert params[17] > 0  # 2026-02-18 is before 2026-03-20


def test_event_to_insert_params_days_zero_for_non_futures():
    """FX/crypto symbol not in expiry_map → $18 is 0."""
    from datetime import UTC, datetime

    from services.feature_writer_service import _event_to_insert_params
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

    event = IntelligenceEvent(
        ts=datetime(2026, 2, 18, 10, 0, 0, tzinfo=UTC),
        symbol="EURUSD",
        tf="5m",
        bar=OHLCVBar(o=1.05, h=1.052, l=1.048, c=1.051, v=1000),
        i1=I1Indicators(rsi_14=50.0),
        i3=I3Structure(),
        i4=I4Context(),
        i5=I5Patterns(),
        smc=SMCContext(),
        i6=I6Confluence(),
    )
    expiry_map = {"ESH6": None}  # EURUSD not in map — returns 0 (non-futures lookup)
    params = _event_to_insert_params(event, expiry_map)

    assert params[17] == 0
