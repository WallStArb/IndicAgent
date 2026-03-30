"""Tests verifying feature_writer_agent._load_config() uses get_active_contracts().

Ensures the default symbol list covers all 23 active H6/J6 contracts rather than
the stale 6-symbol hardcoded list (ESH6, NQH6, RTYH6, CLK6, GCM6, NGK6).
"""

from unittest.mock import patch


def _make_service():
    """Construct FeatureWriterAgent with infrastructure mocked out."""
    # Only patch DatabaseManager - _load_config doesn't need metrics or signal patches
    with patch("services.feature_writer_agent.DatabaseManager"):
        from services.feature_writer_agent import FeatureWriterAgent

        service = FeatureWriterAgent.__new__(FeatureWriterAgent)
        service.config = service._load_config(None)
    return service


def test_default_config_uses_active_contracts():
    """Default config symbols must match get_active_contracts() — not a stale hardcoded list."""
    from src.config.settings import Settings, get_active_contracts

    service = _make_service()

    symbols = service.config["service"]["symbols"]
    active_symbols = [i.symbol for i in get_active_contracts(Settings())]

    # Must contain whichever ES and NQ contracts are currently active
    assert any(s.startswith("ES") for s in symbols), "No ES contract in default symbol list"
    assert any(s.startswith("NQ") for s in symbols), "No NQ contract in default symbol list"
    assert symbols == active_symbols, "feature_writer symbols must exactly match get_active_contracts()"


def test_active_contracts_count():
    """Default symbol list must contain at least 20 entries (all 23 active contracts expected)."""
    service = _make_service()

    symbols = service.config["service"]["symbols"]
    assert (
        len(symbols) >= 20
    ), f"Expected at least 20 active contracts, got {len(symbols)}: {symbols}"
