# tests/unit/core/test_instrument_session.py
import pytest
from src.core.models import Instrument, AssetClass, SESSION_REGISTRY, TradingSession


class TestInstrumentSessionId:
    def test_default_session_id_is_futures(self):
        inst = Instrument(symbol="ES", asset_class=AssetClass.FUTURES)
        assert inst.session_id == "futures_24_5"

    def test_valid_session_id_accepted(self):
        inst = Instrument(symbol="SPY", asset_class=AssetClass.EQUITY, session_id="nyse")
        assert inst.session_id == "nyse"

    def test_invalid_session_id_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="Unknown session_id"):
            Instrument(symbol="SPY", asset_class=AssetClass.EQUITY, session_id="invalid_session")

    def test_trading_session_property_returns_correct_instance(self):
        inst = Instrument(symbol="SPY", asset_class=AssetClass.EQUITY, session_id="nyse")
        session = inst.trading_session
        assert isinstance(session, TradingSession)
        assert session is SESSION_REGISTRY["nyse"]

    def test_all_known_session_ids_valid(self):
        for sid in SESSION_REGISTRY:
            inst = Instrument(symbol="TEST", session_id=sid)
            assert inst.session_id == sid
