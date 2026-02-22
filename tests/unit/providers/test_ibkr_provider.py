import asyncio
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
