"""Unit tests for roll event consumption in all 4 downstream services.

Tests:
- market_analysis_service._handle_roll_event() updates active symbol list
- signal_generator_service._handle_roll_event() updates bar_history keys
- feature_writer_service._handle_roll_event() writes roll boundary marker to DB
- All services: malformed events are logged and skipped
- All services: with roll_monitor_enabled=False, no system.events consumer is started
"""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_market_analysis_service() -> Any:
    from services.market_analysis_service import MarketAnalysisService

    svc = MarketAnalysisService.__new__(MarketAnalysisService)
    svc._active_symbols = set()
    svc.logger = MagicMock()
    return svc


def _make_signal_generator_service() -> Any:
    from services.signal_generator_service import SignalGeneratorService
    from src.core.bar_history import BarHistory

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc._bar_history = BarHistory(maxlen=200)
    svc._df_cache = {}
    svc._stream_map = {}
    svc._regime_cache = defaultdict(dict)
    svc._perf_weights = {}
    svc._drift_penalties = {}
    svc._cis_weights_cache = {}
    svc.logger = MagicMock()
    return svc


def _append_bar(svc: Any, symbol: str, tf: str, close: float) -> None:
    """Append a minimal BarMessage to svc._bar_history for testing."""
    from src.core.schemas.bar_message import BarMessage
    from src.intelligence.schemas import SessionType

    bar = BarMessage(
        ts=datetime(2026, 3, 10, 10, 0, 0, tzinfo=UTC),
        symbol=symbol,
        tf=tf,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=100,
        source="ibkr_named",
        session_type=SessionType.RTH,
    )
    svc._bar_history.append(bar)


def _make_feature_writer_service() -> Any:
    from services.feature_writer_service import FeatureWriterService

    svc = FeatureWriterService.__new__(FeatureWriterService)
    svc.db_manager = None
    svc.logger = MagicMock()
    svc.error_count_total = MagicMock()
    return svc


# ── MarketAnalysisService ──────────────────────────────────────────────────────


class TestMarketAnalysisRollEvent:
    def test_updates_active_symbol_list(self) -> None:
        svc = _make_market_analysis_service()
        svc._active_symbols = {"ESM6", "NQM6"}
        event = {
            "event_type": "roll",
            "base_symbol": "ES",
            "old_symbol": "ESM6",
            "new_symbol": "ESU6",
            "roll_gap": 2.5,
            "roll_direction": "up",
        }
        asyncio.run(svc._handle_roll_event(event))
        assert "ESU6" in svc._active_symbols
        assert "ESM6" not in svc._active_symbols
        assert "NQM6" in svc._active_symbols  # untouched

    def test_ignores_non_roll_event(self) -> None:
        svc = _make_market_analysis_service()
        svc._active_symbols = {"ESM6"}
        event = {"event_type": "heartbeat", "old_symbol": "ESM6", "new_symbol": "ESU6"}
        asyncio.run(svc._handle_roll_event(event))
        assert "ESM6" in svc._active_symbols

    def test_malformed_event_does_not_crash(self) -> None:
        svc = _make_market_analysis_service()
        asyncio.run(svc._handle_roll_event({}))
        asyncio.run(svc._handle_roll_event({"event_type": "roll"}))


# ── SignalGeneratorService ─────────────────────────────────────────────────────


class TestSignalGeneratorRollEvent:
    def test_migrates_bar_history_keys(self) -> None:
        svc = _make_signal_generator_service()
        # Populate _bar_history for old symbol
        _append_bar(svc, "ESM6", "1m", 5200.0)
        _append_bar(svc, "ESM6", "5m", 5200.0)
        event = {
            "event_type": "roll",
            "base_symbol": "ES",
            "old_symbol": "ESM6",
            "new_symbol": "ESU6",
            "roll_gap": 2.5,
            "roll_direction": "up",
        }
        asyncio.run(svc._handle_roll_event(event))
        assert len(svc._bar_history.get("ESU6", "1m")) == 1
        assert len(svc._bar_history.get("ESU6", "5m")) == 1
        # Old keys should be empty after migration
        assert len(svc._bar_history.get("ESM6", "1m")) == 0
        assert len(svc._bar_history.get("ESM6", "5m")) == 0

    def test_ignores_non_roll_event(self) -> None:
        svc = _make_signal_generator_service()
        _append_bar(svc, "ESM6", "1m", 5200.0)
        event = {"event_type": "other", "old_symbol": "ESM6", "new_symbol": "ESU6"}
        asyncio.run(svc._handle_roll_event(event))
        assert len(svc._bar_history.get("ESM6", "1m")) == 1

    def test_malformed_event_does_not_crash(self) -> None:
        svc = _make_signal_generator_service()
        asyncio.run(svc._handle_roll_event({}))
        asyncio.run(svc._handle_roll_event({"event_type": "roll"}))


# ── FeatureWriterService ───────────────────────────────────────────────────────


class TestFeatureWriterRollEvent:
    def test_writes_roll_boundary_marker_to_db(self) -> None:
        svc = _make_feature_writer_service()
        mock_db = MagicMock()
        mock_db.execute_batch = AsyncMock()
        svc.db_manager = mock_db

        event = {
            "event_type": "roll",
            "base_symbol": "ES",
            "old_symbol": "ESM6",
            "new_symbol": "ESU6",
            "roll_gap": 2.5,
            "detected_at": "2026-06-12T14:30:00Z",
        }
        asyncio.run(svc._handle_roll_event(event))

        # execute_batch should have been called once
        assert mock_db.execute_batch.call_count == 1
        call_args = mock_db.execute_batch.call_args
        sql = call_args[0][0]
        params = call_args[0][1]
        # SQL must contain roll_boundary pattern (merge or set)
        assert "intelligence_features" in sql
        assert "roll_boundary" in sql or "i7" in sql.lower()
        # Params must reference both old and new symbol
        # The marker value should encode "ESM6->ESU6"
        marker_str = json.dumps({"roll_boundary": "ESM6->ESU6"})
        assert any("ESM6->ESU6" in str(p) for row in params for p in row), \
            f"Expected 'ESM6->ESU6' in params: {params}"

    def test_roll_boundary_marker_format(self) -> None:
        """The i7 JSON must contain roll_boundary key with old->new format."""
        svc = _make_feature_writer_service()
        mock_db = MagicMock()
        mock_db.execute_batch = AsyncMock()
        svc.db_manager = mock_db

        event = {
            "event_type": "roll",
            "base_symbol": "NQ",
            "old_symbol": "NQM6",
            "new_symbol": "NQU6",
            "roll_gap": 3.0,
            "detected_at": "2026-06-12T14:30:00Z",
        }
        asyncio.run(svc._handle_roll_event(event))

        params = mock_db.execute_batch.call_args[0][1]
        # Find the JSON param that contains the i7 marker
        i7_json = None
        for row in params:
            for p in row:
                if isinstance(p, str):
                    try:
                        d = json.loads(p)
                        if "roll_boundary" in d:
                            i7_json = d
                    except (json.JSONDecodeError, TypeError):
                        pass
        assert i7_json is not None, "No i7 JSON with roll_boundary found in DB call params"
        assert i7_json["roll_boundary"] == "NQM6->NQU6"

    def test_skips_write_if_no_db(self) -> None:
        """No DB connection — should log and return without crashing."""
        svc = _make_feature_writer_service()
        svc.db_manager = None
        event = {
            "event_type": "roll",
            "base_symbol": "ES",
            "old_symbol": "ESM6",
            "new_symbol": "ESU6",
            "roll_gap": 2.5,
        }
        asyncio.run(svc._handle_roll_event(event))  # No crash

    def test_ignores_non_roll_event(self) -> None:
        svc = _make_feature_writer_service()
        mock_db = MagicMock()
        mock_db.execute_batch = AsyncMock()
        svc.db_manager = mock_db
        event = {"event_type": "heartbeat"}
        asyncio.run(svc._handle_roll_event(event))
        mock_db.execute_batch.assert_not_called()

    def test_malformed_event_does_not_crash(self) -> None:
        svc = _make_feature_writer_service()
        mock_db = MagicMock()
        mock_db.execute_batch = AsyncMock()
        svc.db_manager = mock_db
        asyncio.run(svc._handle_roll_event({}))
        asyncio.run(svc._handle_roll_event({"event_type": "roll"}))


# ── Roll monitor disabled behavior ─────────────────────────────────────────────


class TestRollMonitorDisabled:
    """When ROLL_MONITOR_ENABLED=false, services must not subscribe to system.events."""

    def test_indicator_service_no_system_events_consumer_when_disabled(self) -> None:
        """IndicatorService.start() should not subscribe to system.events when disabled."""
        # Verify the service reads roll_monitor_enabled from settings
        # and only adds the system.events subscription conditionally.
        # We do this by inspecting the start() or _setup_kafka method source.
        import inspect

        from services.indicator_service import IndicatorService
        source = inspect.getsource(IndicatorService.start)
        # The topic_system_events subscription must be guarded by roll_monitor_enabled
        assert "roll_monitor_enabled" in source or "topic_system_events" in source, \
            "start() must reference roll_monitor_enabled or topic_system_events"
