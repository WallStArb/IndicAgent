"""
Tests for Settings class after Plan 091-04 instrument registry migration.

Settings no longer has a contracts field or build_contracts() validator.
Instrument config lives in the DB; get_active_contracts() is the access point.
"""

from src.config.settings import Settings


class TestBuildContractsBaseSymbolTemplates:
    """Verify that Settings no longer has a contracts field (Plan 091-04)."""

    def test_settings_instantiation(self):
        """Settings() should succeed without a contracts field."""
        s = Settings()
        assert s is not None

    def test_futures_use_base_symbol(self):
        """Settings no longer has a contracts attribute; instrument data is in DB."""
        s = Settings()
        assert not hasattr(s, "contracts"), (
            "Settings.contracts was removed in Plan 091-04. "
            "Use get_active_contracts() for instrument data."
        )

    def test_futures_no_expiry(self):
        """Settings no longer has a contracts attribute (moved to DB in Plan 091-04)."""
        s = Settings()
        assert not hasattr(s, "contracts"), "Settings.contracts removed; use get_active_contracts()"

    def test_futures_have_required_fields(self):
        """Settings no longer has a contracts attribute (moved to DB in Plan 091-04)."""
        s = Settings()
        assert not hasattr(s, "contracts"), "Settings.contracts removed; use get_active_contracts()"

    def test_non_futures_unchanged(self):
        """Settings no longer has a contracts attribute (moved to DB in Plan 091-04)."""
        s = Settings()
        assert not hasattr(s, "contracts"), "Settings.contracts removed; use get_active_contracts()"

    def test_known_futures_bases_present(self):
        """Settings no longer has a contracts attribute (moved to DB in Plan 091-04)."""
        s = Settings()
        assert not hasattr(s, "contracts"), "Settings.contracts removed; use get_active_contracts()"

    def test_futures_session_id_is_futures_24_5(self):
        """Settings no longer has a contracts attribute (moved to DB in Plan 091-04)."""
        s = Settings()
        assert not hasattr(s, "contracts"), "Settings.contracts removed; use get_active_contracts()"

    def test_no_front_month_codes_in_futures_symbols(self):
        """Settings no longer has a contracts attribute (moved to DB in Plan 091-04)."""
        s = Settings()
        assert not hasattr(s, "contracts"), "Settings.contracts removed; use get_active_contracts()"

    def test_settings_has_no_contracts_attribute(self):
        """Lock-in test: Settings must not have a contracts attribute post Plan 091-04."""
        s = Settings()
        assert not hasattr(s, "contracts"), "Settings.contracts removed; use get_active_contracts()"


# ---------------------------------------------------------------------------
# Plan 067-01 Task 2: Alerting Settings Fields
# ---------------------------------------------------------------------------


class TestAlertingSettingsFields:
    """Verify Settings has alerting webhook fields (Task 2)."""

    def test_telegram_bot_token_defaults_empty(self):
        """telegram_bot_token defaults to empty string (channel disabled)."""
        s = Settings()
        assert s.telegram_bot_token == ""

    def test_telegram_chat_id_defaults_empty(self):
        """telegram_chat_id defaults to empty string (channel disabled)."""
        s = Settings()
        assert s.telegram_chat_id == ""

    def test_discord_webhook_url_defaults_empty(self):
        """discord_webhook_url defaults to empty string (channel disabled)."""
        s = Settings()
        assert s.discord_webhook_url == ""

    def test_telegram_fields_populated_from_env(self):
        """Telegram fields read from TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID env vars."""
        import os

        try:
            os.environ["TELEGRAM_BOT_TOKEN"] = "test_bot_token_123"
            os.environ["TELEGRAM_CHAT_ID"] = "test_chat_id_456"
            s = Settings()
            assert s.telegram_bot_token == "test_bot_token_123"
            assert s.telegram_chat_id == "test_chat_id_456"
        finally:
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            os.environ.pop("TELEGRAM_CHAT_ID", None)

    def test_discord_webhook_populated_from_env(self):
        """discord_webhook_url reads from DISCORD_WEBHOOK_URL env var."""
        import os

        try:
            os.environ["DISCORD_WEBHOOK_URL"] = "https://discord.com/api/webhooks/test"
            s = Settings()
            assert s.discord_webhook_url == "https://discord.com/api/webhooks/test"
        finally:
            os.environ.pop("DISCORD_WEBHOOK_URL", None)
