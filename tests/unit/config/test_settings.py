"""
Unit tests for configuration settings
"""

import os
from unittest.mock import patch

import pytest

from src.config.settings import Settings


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
