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


# ---------------------------------------------------------------------------
# TradingSession, ContractUpdateEvent, and stream_keys tests
# (merged from tests/unit/test_models.py)
# ---------------------------------------------------------------------------

from datetime import UTC, date, datetime

import pytest

from src.core.models import SESSION_REGISTRY
from src.core.schemas.market_events import ContractUpdateEvent
from src.core.stream_keys import topic_contract_updates, topic_roll_dlq


class TestSessionWindowForDate:
    def test_nyse_same_day_monday(self):
        session = SESSION_REGISTRY["nyse"]
        start, end = session.session_window_for_date(date(2026, 3, 23))
        assert start == datetime(2026, 3, 23, 13, 30, tzinfo=UTC)
        assert end == datetime(2026, 3, 23, 20, 0, tzinfo=UTC)

    def test_nyse_saturday_non_trading(self):
        session = SESSION_REGISTRY["nyse"]
        start, end = session.session_window_for_date(date(2026, 3, 21))
        assert start is None and end is None

    def test_nyse_sunday_non_trading(self):
        session = SESSION_REGISTRY["nyse"]
        start, end = session.session_window_for_date(date(2026, 3, 22))
        assert start is None and end is None

    def test_futures_24_5_overnight_monday(self):
        session = SESSION_REGISTRY["futures_24_5"]
        start, end = session.session_window_for_date(date(2026, 3, 23))
        assert start == datetime(2026, 3, 23, 0, 0, tzinfo=UTC)
        assert end == datetime(2026, 3, 23, 23, 0, tzinfo=UTC)

    def test_futures_24_5_saturday_non_trading(self):
        session = SESSION_REGISTRY["futures_24_5"]
        start, end = session.session_window_for_date(date(2026, 3, 21))
        assert start is None and end is None

    def test_futures_24_5_sunday_is_trading(self):
        session = SESSION_REGISTRY["futures_24_5"]
        start, end = session.session_window_for_date(date(2026, 3, 22))
        assert start == datetime(2026, 3, 22, 0, 0, tzinfo=UTC)
        assert end == datetime(2026, 3, 22, 23, 0, tzinfo=UTC)

    def test_crypto_24_7_all_day(self):
        session = SESSION_REGISTRY["crypto_24_7"]
        start, end = session.session_window_for_date(date(2026, 3, 25))
        assert start == datetime(2026, 3, 25, 0, 0, tzinfo=UTC)
        assert end == datetime(2026, 3, 26, 0, 0, tzinfo=UTC)

    def test_crypto_24_7_saturday(self):
        session = SESSION_REGISTRY["crypto_24_7"]
        start, end = session.session_window_for_date(date(2026, 3, 21))
        assert start == datetime(2026, 3, 21, 0, 0, tzinfo=UTC)
        assert end == datetime(2026, 3, 22, 0, 0, tzinfo=UTC)

    def test_fx_24_5_all_day_trading(self):
        session = SESSION_REGISTRY["fx_24_5"]
        start, end = session.session_window_for_date(date(2026, 3, 23))
        assert start == datetime(2026, 3, 23, 0, 0, tzinfo=UTC)
        assert end == datetime(2026, 3, 24, 0, 0, tzinfo=UTC)

    def test_fx_24_5_saturday_non_trading(self):
        session = SESSION_REGISTRY["fx_24_5"]
        start, end = session.session_window_for_date(date(2026, 3, 21))
        assert start is None and end is None

    def test_returns_utc_aware_datetimes(self):
        session = SESSION_REGISTRY["nyse"]
        start, end = session.session_window_for_date(date(2026, 3, 23))
        assert start is not None and start.utcoffset().total_seconds() == 0


class TestMaxAchievablePct:
    def test_nyse_no_breaks(self):
        assert SESSION_REGISTRY["nyse"].max_achievable_pct() == pytest.approx(1.0)

    def test_crypto_24_7(self):
        assert SESSION_REGISTRY["crypto_24_7"].max_achievable_pct() == pytest.approx(1.0)

    def test_futures_24_5(self):
        assert SESSION_REGISTRY["futures_24_5"].max_achievable_pct() == pytest.approx(1.0)

    def test_fx_24_5(self):
        assert SESSION_REGISTRY["fx_24_5"].max_achievable_pct() == pytest.approx(1.0)

    def test_tse_with_break(self):
        pct = SESSION_REGISTRY["tse"].max_achievable_pct()
        assert pct == pytest.approx(330.0 / 390.0, abs=0.01) and pct < 1.0

    def test_hkex_with_break(self):
        pct = SESSION_REGISTRY["hkex"].max_achievable_pct()
        assert pct < 1.0 and pct == pytest.approx(330.0 / 390.0, abs=0.01)

    def test_result_in_valid_range(self):
        for name, session in SESSION_REGISTRY.items():
            pct = session.max_achievable_pct()
            assert 0 < pct <= 1.0, f"Session {name!r} returned {pct!r}"


class TestContractUpdateEvent:
    def test_create_required_fields(self):
        evt = ContractUpdateEvent(
            base_symbol="ES",
            old_contract="ESH6",
            new_contract="ESM6",
            promoted_at=datetime(2026, 3, 16, 12, 0, tzinfo=UTC),
        )
        assert evt.base_symbol == "ES"

    def test_serialize_to_json(self):
        evt = ContractUpdateEvent(
            base_symbol="CL",
            old_contract="CLJ6",
            new_contract="CLK6",
            promoted_at=datetime(2026, 3, 16, 12, 0, tzinfo=UTC),
        )
        d = evt.model_dump(mode="json")
        assert isinstance(d["promoted_at"], str)

    def test_missing_field_raises_validation_error(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ContractUpdateEvent(base_symbol="ES", old_contract="ESH6")


class TestNewStreamKeys:
    def test_topic_contract_updates_empty_env(self):
        assert topic_contract_updates("") == "market.events.contract_update"

    def test_topic_contract_updates_dev_env(self):
        assert topic_contract_updates("dev") == "dev.market.events.contract_update"

    def test_topic_contract_updates_prod_env(self):
        assert topic_contract_updates("prod") == "prod.market.events.contract_update"

    def test_topic_roll_dlq_empty_env(self):
        assert topic_roll_dlq("") == "market.events.roll.dlq"

    def test_topic_roll_dlq_dev_env(self):
        assert topic_roll_dlq("dev") == "dev.market.events.roll.dlq"

    def test_topic_roll_dlq_prod_env(self):
        assert topic_roll_dlq("prod") == "prod.market.events.roll.dlq"
