# tests/unit/providers/test_ibkr_equity.py
from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.models import AssetClass, Instrument

# A falsy return_value=[] is NOT "success" to _fetch_historical_bars_impl -- it's
# ambiguous (no confirmed no-data reqId), so it falls through to a real 65s/130s
# exponential-backoff retry before giving up. TestIBKRUseRTH's tests only assert on
# the useRTH kwarg passed to reqHistoricalDataAsync (already exception-tolerant where
# used), so a truthy stub result is enough to take the immediate-success path and
# skip the retry sleeps entirely.
_IMMEDIATE_SUCCESS_STUB = [MagicMock()]


class TestIBKREquityQualification:
    """IBKR must use secType='STK' for equity instruments."""

    @pytest.mark.asyncio
    async def test_qualify_equity_uses_stock_contract(self):
        from src.providers.ibkr import IBKRProvider

        provider = IBKRProvider.__new__(IBKRProvider)
        provider.logger = MagicMock()
        provider._qualified_contracts = {}
        provider._local_to_canonical = {}

        instrument = Instrument(
            symbol="SPY",
            asset_class=AssetClass.EQUITY,
            exchange="SMART",
            session_id="nyse",
        )

        mock_qualified = MagicMock()
        mock_qualified.secType = "STK"
        mock_qualified.symbol = "SPY"
        mock_qualified.localSymbol = "SPY"

        mock_details = MagicMock()
        mock_details.contract = mock_qualified

        with patch.object(provider, "_ib", create=True) as mock_ib:
            mock_ib.reqContractDetailsAsync = AsyncMock(return_value=[mock_details])
            result = await provider.qualify_instrument(instrument)
            assert result is True
            call_args = mock_ib.reqContractDetailsAsync.call_args
            contract_arg = call_args[0][0]
            assert contract_arg.secType == "STK"


class TestIBKRUseRTH:
    """IBKR must pass useRTH=True for equity historical bars."""

    @pytest.mark.asyncio
    async def test_fetch_equity_bars_uses_rth(self):
        from datetime import datetime

        from src.providers.ibkr import IBKRProvider

        provider = IBKRProvider.__new__(IBKRProvider)
        provider.logger = MagicMock()

        # Pre-populate a qualified STK contract so reqHistoricalDataAsync is reached
        mock_contract = MagicMock()
        mock_contract.secType = "STK"
        provider._qualified_contracts = {"SPY": mock_contract}

        with patch.object(provider, "_ib", create=True) as mock_ib:
            mock_ib.reqHistoricalDataAsync = AsyncMock(return_value=_IMMEDIATE_SUCCESS_STUB)
            start = datetime(2026, 3, 1, tzinfo=UTC)
            end = datetime(2026, 3, 2, tzinfo=UTC)
            try:
                await provider.fetch_historical_bars("SPY", "1m", start, end)
            except Exception:
                pass  # contract not qualified — we only care about useRTH
            assert mock_ib.reqHistoricalDataAsync.called
            call_kwargs = mock_ib.reqHistoricalDataAsync.call_args[1]
            assert call_kwargs.get("useRTH") is True

    @pytest.mark.asyncio
    async def test_fetch_futures_bars_no_rth(self):
        from datetime import datetime

        from src.providers.ibkr import IBKRProvider

        provider = IBKRProvider.__new__(IBKRProvider)
        provider.logger = MagicMock()

        # Pre-populate a qualified FUT contract
        mock_contract = MagicMock()
        mock_contract.secType = "FUT"
        provider._qualified_contracts = {"ES": mock_contract}

        with patch.object(provider, "_ib", create=True) as mock_ib:
            mock_ib.reqHistoricalDataAsync = AsyncMock(return_value=_IMMEDIATE_SUCCESS_STUB)
            start = datetime(2026, 3, 1, tzinfo=UTC)
            end = datetime(2026, 3, 2, tzinfo=UTC)
            try:
                await provider.fetch_historical_bars("ES", "1m", start, end)
            except Exception:
                pass
            assert mock_ib.reqHistoricalDataAsync.called
            call_kwargs = mock_ib.reqHistoricalDataAsync.call_args[1]
            assert call_kwargs.get("useRTH", False) is False
