import asyncio
from datetime import datetime
from unittest.mock import MagicMock, patch, AsyncMock
import pytest
from src.providers.ibkr import IBKRProvider
from src.providers.base import DataProvider


@pytest.fixture
def mock_ib():
    """Mock ib_insync.IB instance."""
    ib = MagicMock()
    ib.isConnected.return_value = True
    ib.pendingTickersEvent = MagicMock()
    return ib


@pytest.fixture
def provider():
    return IBKRProvider(host="127.0.0.1", port=7497, client_id=1)


class TestIBKRProviderProtocol:
    def test_satisfies_data_provider_protocol(self, provider):
        assert isinstance(provider, DataProvider)

    def test_name(self, provider):
        assert provider.name == "ibkr"


class TestConnect:
    @pytest.mark.asyncio
    async def test_connect_success(self, provider, mock_ib):
        with patch("src.providers.ibkr.IB", return_value=mock_ib):
            mock_ib.connect.return_value = None
            mock_ib.isConnected.return_value = True
            result = await provider.connect()
        assert result is True
        assert provider.is_connected()

    @pytest.mark.asyncio
    async def test_connect_failure_returns_false(self, provider, mock_ib):
        with patch("src.providers.ibkr.IB", return_value=mock_ib):
            mock_ib.connect.side_effect = Exception("connection refused")
            result = await provider.connect()
        assert result is False

    @pytest.mark.asyncio
    async def test_disconnect_calls_ib_disconnect(self, provider, mock_ib):
        provider._ib = mock_ib
        await provider.disconnect()
        mock_ib.disconnect.assert_called_once()

    def test_is_connected_false_before_connect(self, provider):
        assert provider.is_connected() is False


class TestFetchHistoricalBars:
    @pytest.mark.asyncio
    async def test_returns_ohlcv_bars(self, provider, mock_ib):
        """fetch_historical_bars maps ib_insync BarData to OHLCVBar list."""
        from datetime import timezone

        mock_bar = MagicMock()
        mock_bar.date = datetime(2026, 2, 1, 9, 30, tzinfo=timezone.utc)
        mock_bar.open = 5100.0
        mock_bar.high = 5105.0
        mock_bar.low = 5098.0
        mock_bar.close = 5102.0
        mock_bar.volume = 1500

        mock_ib.reqHistoricalData.return_value = [mock_bar]
        provider._ib = mock_ib

        mock_contract = MagicMock()
        provider._qualified_contracts["ESH6"] = mock_contract

        bars = await provider.fetch_historical_bars(
            symbol="ESH6",
            timeframe="1m",
            start=datetime(2026, 2, 1, tzinfo=timezone.utc),
            end=datetime(2026, 2, 2, tzinfo=timezone.utc),
        )

        assert len(bars) == 1
        assert bars[0].symbol == "ESH6"
        assert bars[0].timeframe == "1m"
        assert bars[0].open == 5100.0
        assert bars[0].high == 5105.0
        assert bars[0].source == "ibkr"

    @pytest.mark.asyncio
    async def test_unknown_timeframe_raises(self, provider, mock_ib):
        provider._ib = mock_ib
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            await provider.fetch_historical_bars(
                "ESH6", "3m",
                datetime(2026, 2, 1), datetime(2026, 2, 2)
            )

    @pytest.mark.asyncio
    async def test_returns_empty_on_no_data(self, provider, mock_ib):
        from datetime import timezone
        mock_ib.reqHistoricalData.return_value = []
        provider._ib = mock_ib
        provider._qualified_contracts["ESH6"] = MagicMock()
        bars = await provider.fetch_historical_bars(
            "ESH6", "1m",
            datetime(2026, 2, 1, tzinfo=timezone.utc),
            datetime(2026, 2, 2, tzinfo=timezone.utc),
        )
        assert bars == []
