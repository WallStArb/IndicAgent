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
        provider._undefined_contracts = set()

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

    @pytest.mark.asyncio
    async def test_qualify_equity_uses_provider_meta_ibkr_symbol(self):
        from src.providers.ibkr import IBKRProvider

        provider = IBKRProvider.__new__(IBKRProvider)
        provider.logger = MagicMock()
        provider._qualified_contracts = {}
        provider._local_to_canonical = {}
        provider._undefined_contracts = set()

        instrument = Instrument(
            symbol="BRK.B",
            asset_class=AssetClass.EQUITY,
            exchange="SMART",
            session_id="nyse",
            provider_meta={"ibkr": {"symbol": "BRK B"}},
        )
        mock_details = MagicMock()
        mock_details.contract = MagicMock(secType="STK", symbol="BRK B", localSymbol="BRK B")

        with patch.object(provider, "_ib", create=True) as mock_ib:
            mock_ib.reqContractDetailsAsync = AsyncMock(return_value=[mock_details])
            assert await provider.qualify_instrument(instrument) is True
            assert mock_ib.reqContractDetailsAsync.call_args[0][0].symbol == "BRK B"
        assert "BRK.B" in provider._qualified_contracts


class TestIBKRUndefinedContract:
    """Todo 585: is_undefined_contract is True only for IBKR's Error 200 on that symbol's own
    request, so a timeout or another error still reaches the session liveness probe."""

    @staticmethod
    def _provider():
        from src.providers.ibkr import IBKRProvider

        provider = IBKRProvider.__new__(IBKRProvider)
        provider.logger = MagicMock()
        provider._qualified_contracts = {}
        provider._local_to_canonical = {}
        provider._undefined_contracts = set()
        return provider

    _LXP = Instrument(
        symbol="LXP", asset_class=AssetClass.EQUITY, exchange="SMART", session_id="nyse"
    )

    @staticmethod
    def _ib(code: int | None, answer=None, raises: BaseException | None = None):
        """A fake IB whose contract-details call emits `code` for the request's contract."""
        handlers = []

        class _Event:
            def __iadd__(self, handler):
                handlers.append(handler)
                return self

            def __isub__(self, handler):
                handlers.remove(handler)
                return self

        ib = MagicMock()
        ib.errorEvent = _Event()

        async def details(contract):
            if code is not None:
                for handler in list(handlers):
                    handler(7, code, "No security definition has been found", contract)
            if raises is not None:
                raise raises
            return answer if answer is not None else []

        ib.reqContractDetailsAsync = details
        return ib, handlers

    @pytest.mark.asyncio
    async def test_error_200_marks_the_symbol_undefined(self):
        provider = self._provider()
        provider._ib, handlers = self._ib(200)
        assert await provider.qualify_instrument(self._LXP) is False
        assert provider.is_undefined_contract("LXP") and handlers == []

    @pytest.mark.asyncio
    async def test_error_200_raised_as_a_request_error_still_marks_the_symbol(self):
        provider = self._provider()
        provider._ib, _ = self._ib(200, raises=RuntimeError("RequestError 200"))
        assert await provider.qualify_instrument(self._LXP) is False
        assert provider.is_undefined_contract("LXP")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("code, raises", [(None, TimeoutError()), (322, None)])
    async def test_a_timeout_or_another_error_is_not_undefined(self, code, raises):
        provider = self._provider()
        provider._undefined_contracts.add("LXP")  # a previous answer never leaks
        provider._ib, _ = self._ib(code, raises=raises)
        assert await provider.qualify_instrument(self._LXP) is False
        assert not provider.is_undefined_contract("LXP")


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
