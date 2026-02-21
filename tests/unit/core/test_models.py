import pytest
from src.core.models import AssetClass, Instrument


class TestAssetClass:
    def test_all_values_defined(self):
        assert AssetClass.FUTURES == "futures"
        assert AssetClass.EQUITY == "equity"
        assert AssetClass.CRYPTO == "crypto"
        assert AssetClass.FX == "fx"
        assert AssetClass.OPTION == "option"


class TestInstrument:
    def test_futures_instrument(self):
        inst = Instrument(
            symbol="ESH6",
            name="E-mini S&P 500",
            asset_class=AssetClass.FUTURES,
            exchange="CME",
            base="ES",
            expiry="20260320",
            point_value=50.0,
            tick_size=0.25,
            sector="equity_index",
        )
        assert inst.symbol == "ESH6"
        assert inst.asset_class == AssetClass.FUTURES
        assert inst.point_value == 50.0

    def test_equity_instrument_optional_futures_fields(self):
        inst = Instrument(
            symbol="AAPL",
            asset_class=AssetClass.EQUITY,
            exchange="NASDAQ",
        )
        assert inst.base == ""
        assert inst.expiry == ""
        assert inst.point_value == 0

    def test_provider_meta_accepts_arbitrary_dict(self):
        inst = Instrument(
            symbol="BTC/USD",
            asset_class=AssetClass.CRYPTO,
            provider_meta={"product_id": "BTC-USD", "fee_rate": 0.001},
        )
        assert inst.provider_meta["product_id"] == "BTC-USD"

    def test_defaults_to_futures(self):
        inst = Instrument(symbol="NQH6")
        assert inst.asset_class == AssetClass.FUTURES
