"""Tests verifying feature_writer_agent._load_config() uses get_active_contracts().

Ensures the default symbol list covers all active contracts rather than
a stale hardcoded list. Uses mock get_active_contracts() to avoid DB dependency.
"""

from unittest.mock import patch

from src.core.models import AssetClass, Instrument


def _mock_contracts():
    """Return a representative set of active contracts for testing."""
    futures = [
        Instrument(
            symbol="ESM6", base="ES", asset_class=AssetClass.FUTURES, session_id="futures_24_5"
        ),
        Instrument(
            symbol="NQM6", base="NQ", asset_class=AssetClass.FUTURES, session_id="futures_24_5"
        ),
        Instrument(
            symbol="RTYM6", base="RTY", asset_class=AssetClass.FUTURES, session_id="futures_24_5"
        ),
        Instrument(
            symbol="YMM6",
            base="YM",
            asset_class=AssetClass.FUTURES,
            session_id="futures_24_5",
            exchange="CBOT",
        ),
        Instrument(
            symbol="CLM6",
            base="CL",
            asset_class=AssetClass.FUTURES,
            session_id="futures_24_5",
            exchange="NYMEX",
        ),
        Instrument(
            symbol="GCM6",
            base="GC",
            asset_class=AssetClass.FUTURES,
            session_id="futures_24_5",
            exchange="COMEX",
        ),
    ]
    equities = [
        Instrument(symbol="SPY", base="SPY", asset_class=AssetClass.EQUITY, session_id="nyse"),
        Instrument(symbol="QQQ", base="QQQ", asset_class=AssetClass.EQUITY, session_id="nyse"),
    ]
    return futures + equities


def _make_service(mock_contracts=None):
    """Construct FeatureWriter with infrastructure and DB mocked out."""
    if mock_contracts is None:
        mock_contracts = _mock_contracts()

    # Patch both the module-level name in feature_writer_agent AND the settings module
    # so that both get_active_contracts and get_active_symbols calls are covered.
    with (
        patch("services.feature_writer.DatabaseManager"),
        patch("services.feature_writer.get_active_contracts", return_value=mock_contracts),
        patch(
            "services.feature_writer.get_active_symbols",
            return_value=[i.symbol for i in mock_contracts],
        ),
    ):
        from services.feature_writer import FeatureWriter

        service = FeatureWriter.__new__(FeatureWriter)
        service.config = service._load_config(None)
    return service


def test_default_config_uses_active_contracts():
    """Default config symbols must match get_active_contracts() symbols."""
    contracts = _mock_contracts()
    expected_symbols = [i.symbol for i in contracts]

    service = _make_service(mock_contracts=contracts)
    symbols = service.config["service"]["symbols"]

    # Must contain futures symbols from mock
    assert any(s.startswith("ES") for s in symbols), "No ES contract in default symbol list"
    assert any(s.startswith("NQ") for s in symbols), "No NQ contract in default symbol list"
    assert symbols == expected_symbols, "feature_writer symbols must match get_active_contracts()"


def test_active_contracts_count():
    """Default symbol list must contain at least 8 entries (mock returns 8)."""
    service = _make_service()

    symbols = service.config["service"]["symbols"]
    assert len(symbols) >= 8, f"Expected at least 8 active contracts, got {len(symbols)}: {symbols}"
