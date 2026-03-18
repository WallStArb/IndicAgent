"""Unit tests for DB-backed get_active_contracts() and get_active_symbols().

Tests:
- ROLL_MONITOR_ENABLED=false: returns Settings().contracts unchanged (list[Instrument])
- ROLL_MONITOR_ENABLED=true + DB rows: returns DB-sourced Instruments with config defaults
- ROLL_MONITOR_ENABLED=true + DB error: fallback to config-file contracts + WARNING log
- Cache: second call within 60s returns cached result
- Return type: list[Instrument] (NOT list[str])
- get_active_symbols(): returns list[str]
- Returned Instruments have populated exchange/point_value/tick_size/session_id
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from src.config.settings import get_active_contracts, get_active_symbols
from src.core.models import AssetClass, Instrument

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(roll_monitor_enabled: bool = False) -> MagicMock:
    """Build a minimal mock Settings object."""
    mock = MagicMock()
    mock.roll_monitor_enabled = roll_monitor_enabled
    mock.database_url = "postgresql://postgres:postgres@localhost:5432/indicagent"
    # Provide two representative contracts: one futures, one FX
    mock.contracts = [
        Instrument(
            symbol="ESM6",
            base="ES",
            exchange="CME",
            expiry="202606",
            name="E-mini S&P 500",
            point_value=50,
            tick_size=0.25,
            sector="equity_index",
            asset_class=AssetClass.FUTURES,
        ),
        Instrument(
            symbol="EURUSD",
            base="EUR",
            exchange="IDEALPRO",
            sector="fx",
            asset_class=AssetClass.FX,
            session_id="fx_24_5",
            name="Euro/US Dollar",
            point_value=10.0,
            tick_size=0.00001,
        ),
    ]
    return mock


def _reset_cache() -> None:
    """Reset the module-level cache so tests are isolated."""
    import src.config.settings as settings_mod
    settings_mod._active_contracts_cache = None
    settings_mod._active_contracts_last_refresh = 0.0


# ---------------------------------------------------------------------------
# Tests: ROLL_MONITOR_ENABLED=false (default behaviour)
# ---------------------------------------------------------------------------


class TestGetActiveContractsDisabled:
    def setup_method(self):
        _reset_cache()

    def test_returns_list_of_instruments(self):
        """Must return list[Instrument], not list[str]."""
        mock_settings = _make_settings(roll_monitor_enabled=False)
        result = get_active_contracts(mock_settings)
        assert isinstance(result, list)
        assert len(result) > 0
        for item in result:
            assert isinstance(item, Instrument), f"Expected Instrument, got {type(item)}"

    def test_returns_same_contracts_as_settings(self):
        """With roll monitoring disabled, must return settings.contracts unchanged."""
        mock_settings = _make_settings(roll_monitor_enabled=False)
        result = get_active_contracts(mock_settings)
        assert result == list(mock_settings.contracts)

    def test_does_not_query_db(self):
        """No DB connection should be made when ROLL_MONITOR_ENABLED=false."""
        mock_settings = _make_settings(roll_monitor_enabled=False)
        with patch("psycopg2.connect") as mock_conn:
            get_active_contracts(mock_settings)
            mock_conn.assert_not_called()

    def test_get_active_symbols_returns_strings(self):
        """get_active_symbols() convenience wrapper must return list[str]."""
        mock_settings = _make_settings(roll_monitor_enabled=False)
        result = get_active_symbols(mock_settings)
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, str), f"Expected str, got {type(item)}"

    def test_get_active_symbols_matches_instrument_symbols(self):
        """get_active_symbols() must return the same symbol strings as get_active_contracts()."""
        mock_settings = _make_settings(roll_monitor_enabled=False)
        instruments = get_active_contracts(mock_settings)
        symbols = get_active_symbols(mock_settings)
        assert symbols == [i.symbol for i in instruments]


# ---------------------------------------------------------------------------
# Tests: ROLL_MONITOR_ENABLED=true, DB returns rows
# ---------------------------------------------------------------------------


class TestGetActiveContractsDbEnabled:
    def setup_method(self):
        _reset_cache()

    def _make_mock_db_rows(self):
        """Simulate DB returning one futures row."""
        return [("ESM6", "ES", "CME")]

    def test_returns_list_of_instruments_from_db(self):
        """With roll monitoring enabled and DB working, must return list[Instrument]."""
        mock_settings = _make_settings(roll_monitor_enabled=True)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = self._make_mock_db_rows()

        with patch("psycopg2.connect", return_value=mock_conn):
            result = get_active_contracts(mock_settings)

        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, Instrument)

    def test_db_instrument_inherits_config_defaults(self):
        """DB-sourced futures Instrument must have exchange/point_value/tick_size
        inherited from config-file contracts (not empty defaults)."""
        mock_settings = _make_settings(roll_monitor_enabled=True)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [("ESM6", "ES", "CME")]

        with patch("psycopg2.connect", return_value=mock_conn):
            result = get_active_contracts(mock_settings)

        futures = [i for i in result if i.asset_class == AssetClass.FUTURES]
        assert len(futures) >= 1
        es = next((i for i in futures if i.base == "ES" or i.symbol == "ESM6"), None)
        assert es is not None
        # Must have inherited non-zero values from config
        assert es.exchange != "", "exchange must be inherited from config"
        assert es.point_value != 0, "point_value must be inherited from config"
        assert es.tick_size != 0, "tick_size must be inherited from config"
        assert es.session_id != "", "session_id must be inherited from config"

    def test_non_futures_always_from_config(self):
        """Non-futures Instruments (FX, equity, crypto) must always come from config."""
        mock_settings = _make_settings(roll_monitor_enabled=True)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        # DB only returns futures rows
        mock_cursor.fetchall.return_value = [("ESM6", "ES", "CME")]

        with patch("psycopg2.connect", return_value=mock_conn):
            result = get_active_contracts(mock_settings)

        fx = [i for i in result if i.asset_class == AssetClass.FX]
        assert len(fx) >= 1, "FX instruments from config must be included"
        assert fx[0].symbol == "EURUSD"

    def test_queries_is_front_month(self):
        """The DB query must filter by is_front_month = true."""
        mock_settings = _make_settings(roll_monitor_enabled=True)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        with patch("psycopg2.connect", return_value=mock_conn):
            get_active_contracts(mock_settings)

        # Check the SQL executed contains is_front_month
        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "is_front_month" in executed_sql, (
            f"DB query must filter by is_front_month; got SQL: {executed_sql!r}"
        )


# ---------------------------------------------------------------------------
# Tests: ROLL_MONITOR_ENABLED=true, DB error → fallback
# ---------------------------------------------------------------------------


class TestGetActiveContractsDbFallback:
    def setup_method(self):
        _reset_cache()

    def test_db_error_falls_back_to_config(self):
        """On DB connection error, must return config-file contracts (list[Instrument])."""
        mock_settings = _make_settings(roll_monitor_enabled=True)

        with patch("psycopg2.connect", side_effect=Exception("DB connection refused")):
            result = get_active_contracts(mock_settings)

        assert isinstance(result, list)
        assert len(result) > 0
        for item in result:
            assert isinstance(item, Instrument)
        # Should match config contracts
        assert result == list(mock_settings.contracts)

    def test_db_error_returns_instrument_list_not_strings(self):
        """Fallback must still return list[Instrument], not list[str]."""
        mock_settings = _make_settings(roll_monitor_enabled=True)

        with patch("psycopg2.connect", side_effect=Exception("timeout")):
            result = get_active_contracts(mock_settings)

        for item in result:
            assert isinstance(item, Instrument), f"Fallback must return Instrument, got {type(item)}"


# ---------------------------------------------------------------------------
# Tests: cache behaviour
# ---------------------------------------------------------------------------


class TestGetActiveContractsCache:
    def setup_method(self):
        _reset_cache()

    def test_second_call_within_60s_uses_cache(self):
        """Second call within 60 seconds must return cached result without DB query."""
        mock_settings = _make_settings(roll_monitor_enabled=True)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [("ESM6", "ES", "CME")]

        with patch("psycopg2.connect", return_value=mock_conn) as mock_connect:
            result1 = get_active_contracts(mock_settings)
            result2 = get_active_contracts(mock_settings)

        # DB should only be queried once
        assert mock_connect.call_count == 1, (
            f"DB must only be queried once within cache TTL, called {mock_connect.call_count} times"
        )
        assert result1 == result2

    def test_cache_expires_after_60s(self):
        """After forcing cache expiry, next call must re-query the DB."""
        import src.config.settings as settings_mod

        mock_settings = _make_settings(roll_monitor_enabled=True)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [("ESM6", "ES", "CME")]

        with patch("psycopg2.connect", return_value=mock_conn) as mock_connect:
            # First call — populates cache
            get_active_contracts(mock_settings)
            call_count_after_first = mock_connect.call_count

            # Force cache expiry
            settings_mod._active_contracts_last_refresh = time.monotonic() - 61.0

            # Second call — cache expired, must re-query
            get_active_contracts(mock_settings)
            call_count_after_second = mock_connect.call_count

        assert call_count_after_first == 1
        assert call_count_after_second == 2, "DB must be re-queried after cache expires"


# ---------------------------------------------------------------------------
# Tests: return type is always list[Instrument]
# ---------------------------------------------------------------------------


class TestGetActiveContractsReturnType:
    def setup_method(self):
        _reset_cache()

    def test_disabled_mode_not_list_of_str(self):
        """get_active_contracts() must NOT return list[str]."""
        mock_settings = _make_settings(roll_monitor_enabled=False)
        result = get_active_contracts(mock_settings)
        if result:
            assert not isinstance(result[0], str), (
                "get_active_contracts() must return list[Instrument], not list[str]"
            )

    def test_get_active_symbols_returns_list_of_str(self):
        """get_active_symbols() must return list[str]."""
        mock_settings = _make_settings(roll_monitor_enabled=False)
        result = get_active_symbols(mock_settings)
        assert isinstance(result, list)
        if result:
            assert isinstance(result[0], str)

    def test_get_active_symbols_function_exists(self):
        """get_active_symbols must be importable from src.config.settings."""
        from src.config.settings import get_active_symbols as _fn
        assert callable(_fn)
