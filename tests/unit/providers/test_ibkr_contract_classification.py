"""Unit tests: IBKRProvider.fetch_contract_classification (Phase 182, D-06 sourcing path).

Pure unit-test style matching tests/unit/providers/test_ibkr_equity.py: constructs
IBKRProvider via __new__, patches `_ib` with a MagicMock, asserts on the resulting
ContractClassification / exception behavior. No live IBKR connection.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _provider_with_fake_ib(details_return_value):
    from src.providers.ibkr import IBKRProvider

    provider = IBKRProvider.__new__(IBKRProvider)
    provider.logger = MagicMock()
    provider._qualified_contracts = {}
    provider._local_to_canonical = {}
    provider._ib = MagicMock()
    provider._ib.reqContractDetailsAsync = AsyncMock(return_value=details_return_value)
    return provider


class TestFetchContractClassification:
    @pytest.mark.asyncio
    async def test_returns_classification_for_single_details_result(self):
        from src.providers.ibkr import ContractClassification

        details = MagicMock()
        details.industry = "Technology"
        details.category = "Semiconductors"
        details.subcategory = "Electronic Compo-Semicon"
        details.longName = "NVIDIA CORP"

        provider = _provider_with_fake_ib([details])
        result = await provider.fetch_contract_classification("NVDA")

        assert result == ContractClassification(
            symbol="NVDA",
            industry="Technology",
            category="Semiconductors",
            subcategory="Electronic Compo-Semicon",
            long_name="NVIDIA CORP",
        )

    @pytest.mark.asyncio
    async def test_contract_passed_is_stock_smart_usd(self):
        details = MagicMock()
        details.industry = "Technology"
        details.category = "Semiconductors"
        details.subcategory = "Electronic Compo-Semicon"
        details.longName = "NVIDIA CORP"

        provider = _provider_with_fake_ib([details])
        await provider.fetch_contract_classification("NVDA")

        call_args = provider._ib.reqContractDetailsAsync.call_args
        contract_arg = call_args[0][0]
        assert contract_arg.secType == "STK"
        assert contract_arg.symbol == "NVDA"
        assert contract_arg.exchange == "SMART"
        assert contract_arg.currency == "USD"

    @pytest.mark.asyncio
    async def test_empty_details_returns_none(self):
        provider = _provider_with_fake_ib([])
        result = await provider.fetch_contract_classification("NOSYM")
        assert result is None

    @pytest.mark.asyncio
    async def test_two_details_with_same_triple_returns_first(self):
        from src.providers.ibkr import ContractClassification

        d1 = MagicMock()
        d1.industry = "Technology"
        d1.category = "Semiconductors"
        d1.subcategory = "Electronic Compo-Semicon"
        d1.longName = "NVIDIA CORP"

        d2 = MagicMock()
        d2.industry = "Technology"
        d2.category = "Semiconductors"
        d2.subcategory = "Electronic Compo-Semicon"
        d2.longName = "NVIDIA CORP DUPLICATE LISTING"

        provider = _provider_with_fake_ib([d1, d2])
        result = await provider.fetch_contract_classification("NVDA")

        assert result == ContractClassification(
            symbol="NVDA",
            industry="Technology",
            category="Semiconductors",
            subcategory="Electronic Compo-Semicon",
            long_name="NVIDIA CORP",
        )

    @pytest.mark.asyncio
    async def test_two_details_with_different_triples_raises_value_error_naming_symbol(self):
        d1 = MagicMock()
        d1.industry = "Technology"
        d1.category = "Semiconductors"
        d1.subcategory = "Electronic Compo-Semicon"
        d1.longName = "AMBIG CORP A"

        d2 = MagicMock()
        d2.industry = "Financials"
        d2.category = "Banks"
        d2.subcategory = "Regional Banks"
        d2.longName = "AMBIG CORP B"

        provider = _provider_with_fake_ib([d1, d2])

        with pytest.raises(ValueError, match="AMBIG"):
            await provider.fetch_contract_classification("AMBIG")

    @pytest.mark.asyncio
    async def test_missing_attributes_default_to_empty_string(self):
        # A details object with no industry/category/subcategory/longName attrs at all
        # (e.g. a bare object()) must not raise AttributeError -- getattr default "".
        details = object()

        provider = _provider_with_fake_ib([details])
        result = await provider.fetch_contract_classification("BARE")

        from src.providers.ibkr import ContractClassification

        assert result == ContractClassification(
            symbol="BARE", industry="", category="", subcategory="", long_name=""
        )

    @pytest.mark.asyncio
    async def test_calling_before_connect_raises_runtime_error(self):
        from src.providers.ibkr import IBKRProvider

        provider = IBKRProvider.__new__(IBKRProvider)
        provider.logger = MagicMock()
        provider._qualified_contracts = {}
        provider._local_to_canonical = {}
        provider._ib = None

        with pytest.raises(RuntimeError):
            await provider.fetch_contract_classification("NVDA")

    @pytest.mark.asyncio
    async def test_timeout_propagates_and_is_not_swallowed(self):
        import src.providers.ibkr as ibkr_module

        provider = _provider_with_fake_ib([])

        async def _never_resolves(*args, **kwargs):
            import asyncio

            await asyncio.sleep(10)

        provider._ib.reqContractDetailsAsync = _never_resolves

        with patch.object(ibkr_module, "_CONTRACT_DETAILS_TIMEOUT_SEC", 0.01):
            with pytest.raises(TimeoutError):
                await provider.fetch_contract_classification("SLOWSYM")
