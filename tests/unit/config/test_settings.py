"""
Unit tests for configuration settings
"""

import os
from unittest.mock import patch

import pytest

from src.config.settings import (
    Settings,
    get_active_contracts,
    get_base_symbols,
    get_contract_info,
    get_point_value,
    get_tick_size,
)
from src.core.models import Instrument


class TestSettings:
    """Test Settings configuration functionality"""

    @pytest.mark.unit
    def test_default_settings(self):
        """Test default settings initialization"""
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)

            assert settings.env_name == ""
            assert settings.database_url is not None
            assert settings.redis_host == "localhost"
            assert settings.redis_port == 6379

    @pytest.mark.unit
    def test_environment_override(self):
        """Test environment variable override"""
        test_env = {
            "INDICAGENT_ENV": "production",
            "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
        }

        with patch.dict(os.environ, test_env, clear=True):
            settings = Settings()

            assert settings.env_name == "production"
            assert "test:test@localhost:5432/test" in settings.database_url

    @pytest.mark.unit
    def test_ibkr_settings(self):
        """Test IBKR connection settings"""
        settings = Settings()

        assert hasattr(settings, "ib_host")
        assert hasattr(settings, "ib_port")
        assert isinstance(settings.ib_port, int)

    @pytest.mark.unit
    def test_metrics_settings(self):
        """Test metrics configuration"""
        settings = Settings()

        assert hasattr(settings, "metrics_port")
        assert isinstance(settings.metrics_port, int)


class TestIBKRContractMetadata:
    """Test extended IBKRContract model fields."""

    @pytest.mark.unit
    def test_default_contracts_have_metadata(self):
        """All default contracts should have name, point_value, tick_size, sector."""
        settings = Settings(_env_file=None)
        assert len(settings.contracts) >= 14
        for c in settings.contracts:
            assert c.name, f"{c.symbol} missing name"
            assert c.point_value > 0, f"{c.symbol} missing point_value"
            assert c.tick_size > 0, f"{c.symbol} missing tick_size"
            assert c.sector, f"{c.symbol} missing sector"

    @pytest.mark.unit
    def test_contract_sectors(self):
        """Contracts should cover expected sectors (equity, energy, metals, rates, ag, etc.)."""
        settings = Settings(_env_file=None)
        sectors = {c.sector for c in settings.contracts}
        assert "equity_index" in sectors
        assert "energy" in sectors
        assert "metals" in sectors
        assert "volatility" in sectors
        assert "interest_rates" in sectors

    @pytest.mark.unit
    def test_contract_metadata_values(self):
        """Spot-check specific contract metadata."""
        settings = Settings(_env_file=None)
        by_base = {c.base: c for c in settings.contracts}

        es = by_base["ES"]
        assert es.name == "E-mini S&P 500"
        assert es.point_value == 50
        assert es.tick_size == 0.25
        assert es.sector == "equity_index"

        gc = by_base["GC"]
        assert gc.name == "Gold"
        assert gc.point_value == 100
        assert gc.tick_size == 0.10

        zn = by_base["ZN"]
        assert zn.name == "10-Year T-Note"
        assert zn.point_value == 1000
        assert zn.tick_size == 0.015625
        assert zn.sector == "interest_rates"

    @pytest.mark.unit
    def test_ibkr_contract_defaults(self):
        """New fields should have sensible defaults for backwards compat."""
        c = Instrument(symbol="TEST", base="T", exchange="X", expiry="20260101")
        assert c.name == ""
        assert c.point_value == 0
        assert c.tick_size == 0
        assert c.sector == ""


class TestHelperFunctions:
    """Test module-level instrument helper functions."""

    @pytest.mark.unit
    def test_get_active_contracts(self):
        """Should return contract symbol strings (at least original 14)."""
        settings = Settings(_env_file=None)
        contracts = get_active_contracts(settings)
        assert len(contracts) >= 14
        assert "ESH6" in contracts
        assert "ZTH6" in contracts
        assert all(isinstance(s, str) for s in contracts)

    @pytest.mark.unit
    def test_get_base_symbols(self):
        """Should return unique base symbols preserving order."""
        settings = Settings(_env_file=None)
        bases = get_base_symbols(settings)
        assert len(bases) >= 14
        assert bases[0] == "ES"
        assert "ZT" in bases
        # VIX is the IBKR base symbol, not VX
        assert "VIX" in bases

    @pytest.mark.unit
    def test_get_contract_info_by_symbol(self):
        """Lookup by full contract symbol."""
        settings = Settings(_env_file=None)
        c = get_contract_info("ESH6", settings)
        assert c is not None
        assert c.base == "ES"
        assert c.name == "E-mini S&P 500"

    @pytest.mark.unit
    def test_get_contract_info_by_base(self):
        """Lookup by base symbol."""
        settings = Settings(_env_file=None)
        c = get_contract_info("GC", settings)
        assert c is not None
        assert c.symbol == "GCJ6"
        assert c.name == "Gold"

    @pytest.mark.unit
    def test_get_contract_info_not_found(self):
        """Unknown symbol returns None."""
        settings = Settings(_env_file=None)
        assert get_contract_info("FAKE", settings) is None

    @pytest.mark.unit
    def test_get_point_value(self):
        settings = Settings(_env_file=None)
        assert get_point_value("ES", settings) == 50
        assert get_point_value("CLJ6", settings) == 1000
        assert get_point_value("FAKE", settings) is None

    @pytest.mark.unit
    def test_get_tick_size(self):
        settings = Settings(_env_file=None)
        assert get_tick_size("NQ", settings) == 0.25
        assert get_tick_size("NGJ6", settings) == 0.001
        assert get_tick_size("FAKE", settings) is None
