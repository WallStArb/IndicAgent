"""Unit tests for WarmupProvider and FeatureSnapshotRepository."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.persistence.logic.warmup_provider import WarmupProvider
from src.persistence.repository.feature_snapshot_repository import FeatureSnapshotRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(db_url: str = "postgresql://localhost/test") -> MagicMock:
    s = MagicMock()
    s.database_url = db_url
    s.env_name = "development"
    return s


def _make_config(symbols=("ES",), timeframes=("1m",)) -> dict:
    return {"service": {"symbols": list(symbols), "timeframes": list(timeframes)}}


def _make_feature_row(symbol: str = "ES", tf: str = "1m") -> dict:
    ts = datetime(2026, 3, 26, 10, 0, tzinfo=UTC)
    return {
        "ts": ts,
        "bar": {"o": 5100.0, "h": 5110.0, "l": 5095.0, "c": 5105.0, "v": 1000},
        "i1": {},
        "i2": {},
        "i3": {},
        "i4": {},
        "i5": {},
        "smc": {},
        "i6": {},
        "bar_close_ts": ts,
        "i1_computed_at": ts,
        "computed_at": ts,
    }


def _make_ohlcv_row() -> dict:
    return {
        "timestamp": datetime(2026, 3, 26, 9, 59, tzinfo=UTC),
        "open": 5098.0,
        "high": 5102.0,
        "low": 5096.0,
        "close": 5100.0,
        "volume": 800,
    }


# ---------------------------------------------------------------------------
# FeatureSnapshotRepository
# ---------------------------------------------------------------------------

class TestFeatureSnapshotRepository:
    @pytest.fixture
    def db(self):
        mock = MagicMock()
        mock.execute_query = AsyncMock(return_value=[])
        return mock

    def test_get_recent_features_builds_correct_query(self, db):
        repo = FeatureSnapshotRepository(db)
        asyncio.run(
            repo.get_recent_features("ES", "1m", 50, 3600)
        )
        db.execute_query.assert_awaited_once()
        call_args = db.execute_query.call_args
        sql = call_args[0][0]
        assert "intelligence_features" in sql
        assert "ORDER BY ts DESC" in sql
        assert call_args[0][1] == "ES"
        assert call_args[0][2] == "1m"

    def test_get_recent_features_returns_empty_on_error(self, db):
        db.execute_query = AsyncMock(side_effect=Exception("connection refused"))
        repo = FeatureSnapshotRepository(db)
        result = asyncio.get_event_loop().run_until_complete(
            repo.get_recent_features("ES", "1m", 50, 3600)
        )
        assert result == []

    def test_get_ohlcv_fallback_builds_correct_query(self, db):
        repo = FeatureSnapshotRepository(db)
        asyncio.run(
            repo.get_ohlcv_fallback("ES", "5m", 30, 7200)
        )
        db.execute_query.assert_awaited_once()
        sql = db.execute_query.call_args[0][0]
        assert "market_data_ohlcv" in sql
        assert "ORDER BY timestamp DESC" in sql

    def test_get_ohlcv_fallback_returns_empty_on_error(self, db):
        db.execute_query = AsyncMock(side_effect=RuntimeError("timeout"))
        repo = FeatureSnapshotRepository(db)
        result = asyncio.get_event_loop().run_until_complete(
            repo.get_ohlcv_fallback("ES", "1m", 50, 3600)
        )
        assert result == []


# ---------------------------------------------------------------------------
# WarmupProvider — seed()
# ---------------------------------------------------------------------------

class TestWarmupProviderSeed:
    @pytest.fixture
    def kafka_producer(self):
        mock = MagicMock()
        mock.publish = AsyncMock()
        return mock

    @pytest.fixture
    def bar_history(self):
        return defaultdict(lambda: deque(maxlen=200))

    def _run(self, coro):
        return asyncio.run(coro)

    # ------------------------------------------------------------------
    # No DB URL — skip gracefully
    # ------------------------------------------------------------------

    def test_seed_skips_when_no_db_url(self, kafka_producer, bar_history):
        settings = _make_settings(db_url="")
        provider = WarmupProvider(settings, _make_config(), kafka_producer)
        self._run(provider.seed(bar_history))
        kafka_producer.publish.assert_not_awaited()

    # ------------------------------------------------------------------
    # DB unavailable — all retries exhausted, non-fatal
    # ------------------------------------------------------------------

    def test_seed_non_fatal_when_db_unavailable(self, kafka_producer, bar_history):
        settings = _make_settings()
        provider = WarmupProvider(settings, _make_config(), kafka_producer)

        with patch(
            "src.persistence.logic.warmup_provider.DatabaseManager"
        ) as MockDB, patch(
            "src.persistence.logic.warmup_provider.asyncio.sleep", new=AsyncMock()
        ):
            MockDB.return_value.initialize = AsyncMock(side_effect=Exception("refused"))
            self._run(provider.seed(bar_history))

        assert len(bar_history) == 0
        kafka_producer.publish.assert_not_awaited()

    # ------------------------------------------------------------------
    # Successful seed — bar_history populated and event published
    # ------------------------------------------------------------------

    def test_seed_populates_bar_history(self, kafka_producer, bar_history):
        settings = _make_settings()
        config = _make_config(symbols=("ES",), timeframes=("1m",))
        provider = WarmupProvider(settings, config, kafka_producer)

        rows = [_make_feature_row()]

        with patch(
            "src.persistence.logic.warmup_provider.DatabaseManager"
        ) as MockDB, patch(
            "src.persistence.logic.warmup_provider.get_active_symbols",
            return_value=["ES"],
        ), patch(
            "src.persistence.logic.warmup_provider.FeatureSnapshotRepository"
        ) as MockRepo:
            MockDB.return_value.initialize = AsyncMock()
            MockDB.return_value.close = AsyncMock()
            mock_repo = MagicMock()
            mock_repo.get_recent_features = AsyncMock(return_value=rows)
            mock_repo.get_ohlcv_fallback = AsyncMock(return_value=[])
            MockRepo.return_value = mock_repo

            self._run(provider.seed(bar_history))

        assert len(bar_history["ES:1m"]) == 1
        bar = bar_history["ES:1m"][0]
        assert bar["open"] == 5100.0
        assert bar["close"] == 5105.0

    def test_seed_publishes_latest_intelligence_event(self, kafka_producer, bar_history):
        settings = _make_settings()
        config = _make_config(symbols=("ES",), timeframes=("1m",))
        provider = WarmupProvider(settings, config, kafka_producer)

        rows = [_make_feature_row()]

        with patch(
            "src.persistence.logic.warmup_provider.DatabaseManager"
        ) as MockDB, patch(
            "src.persistence.logic.warmup_provider.get_active_symbols",
            return_value=["ES"],
        ), patch(
            "src.persistence.logic.warmup_provider.FeatureSnapshotRepository"
        ) as MockRepo:
            MockDB.return_value.initialize = AsyncMock()
            MockDB.return_value.close = AsyncMock()
            mock_repo = MagicMock()
            mock_repo.get_recent_features = AsyncMock(return_value=rows)
            mock_repo.get_ohlcv_fallback = AsyncMock(return_value=[])
            MockRepo.return_value = mock_repo

            self._run(provider.seed(bar_history))

        kafka_producer.publish.assert_awaited_once()

    def test_seed_uses_ohlcv_fallback_when_features_empty(self, kafka_producer, bar_history):
        settings = _make_settings()
        config = _make_config(symbols=("ES",), timeframes=("1m",))
        provider = WarmupProvider(settings, config, kafka_producer)

        with patch(
            "src.persistence.logic.warmup_provider.DatabaseManager"
        ) as MockDB, patch(
            "src.persistence.logic.warmup_provider.get_active_symbols",
            return_value=["ES"],
        ), patch(
            "src.persistence.logic.warmup_provider.FeatureSnapshotRepository"
        ) as MockRepo:
            MockDB.return_value.initialize = AsyncMock()
            MockDB.return_value.close = AsyncMock()
            mock_repo = MagicMock()
            mock_repo.get_recent_features = AsyncMock(return_value=[])
            mock_repo.get_ohlcv_fallback = AsyncMock(return_value=[_make_ohlcv_row()])
            MockRepo.return_value = mock_repo

            self._run(provider.seed(bar_history))

        # No intelligence rows → no event published
        kafka_producer.publish.assert_not_awaited()
        # But bar_history populated from ohlcv fallback
        assert len(bar_history["ES:1m"]) == 1

    def test_seed_closes_db_connection_on_success(self, kafka_producer, bar_history):
        settings = _make_settings()
        config = _make_config(symbols=("ES",), timeframes=("1m",))
        provider = WarmupProvider(settings, config, kafka_producer)

        with patch(
            "src.persistence.logic.warmup_provider.DatabaseManager"
        ) as MockDB, patch(
            "src.persistence.logic.warmup_provider.get_active_symbols",
            return_value=["ES"],
        ), patch(
            "src.persistence.logic.warmup_provider.FeatureSnapshotRepository"
        ) as MockRepo:
            MockDB.return_value.initialize = AsyncMock()
            close_mock = AsyncMock()
            MockDB.return_value.close = close_mock
            mock_repo = MagicMock()
            mock_repo.get_recent_features = AsyncMock(return_value=[])
            mock_repo.get_ohlcv_fallback = AsyncMock(return_value=[])
            MockRepo.return_value = mock_repo

            self._run(provider.seed(bar_history))

        close_mock.assert_awaited_once()
