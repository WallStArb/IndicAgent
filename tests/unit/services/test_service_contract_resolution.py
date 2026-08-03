"""Unit tests for DB-backed get_active_contracts() and get_active_symbols().

Tests:
- get_active_contracts() queries contract_metadata (futures) AND instruments (non-futures)
- DB rows present: returns DB-sourced Instruments with config defaults
- DB error (cold cache): returns empty list + CRITICAL log
- DB error (warm cache): returns cached value
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


def _make_settings() -> MagicMock:
    """Build a minimal mock Settings object."""
    mock = MagicMock()
    mock.database_url = "postgresql://postgres:postgres@localhost:5432/indicagent"
    return mock


def _reset_cache() -> None:
    """Reset the module-level cache so tests are isolated."""
    import src.config.settings as settings_mod

    settings_mod._active_contracts_cache = None
    settings_mod._active_contracts_last_refresh = 0.0


def _make_mock_db_conn(futures_rows: list, non_futures_rows: list | None = None) -> MagicMock:
    """Build a single psycopg connection mock for get_active_contracts().

    get_active_contracts() uses ONE psycopg.connect() that runs three queries
    in sequence on the same cursor:
      1. Load futures templates from instruments table (asset_class='futures')
      2. Query contract_metadata for front-month futures symbols
      3. Query instruments for non-futures (is_active=true, asset_class!='futures')

    Returns a single mock connection. Use with patch("psycopg.connect", return_value=conn).
    """
    if non_futures_rows is None:
        non_futures_rows = []

    # Futures templates: one ES row in instruments (asset_class='futures')
    es_template = (
        "ES",
        "ES",
        {
            "symbol": "ES",
            "base": "ES",
            "name": "E-mini S&P 500",
            "asset_class": "futures",
            "exchange": "CME",
            "sector": "equity_index",
            "tick_size": 0.25,
            "point_value": 50.0,
            "session_id": "futures_24_5",
            "provider_meta": {},
            "expiry": "",
        },
    )

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cursor
    # Three sequential fetchall() calls: templates, futures, non-futures
    mock_cursor.fetchall.side_effect = [[es_template], futures_rows, non_futures_rows]
    return mock_conn


# Sample non-futures row: (symbol, base, contract_details dict)
_EURUSD_NF_ROW = (
    "EURUSD",
    "EUR",
    {
        "symbol": "EURUSD",
        "base": "EUR",
        "name": "Euro/US Dollar",
        "asset_class": "fx",
        "exchange": "IDEALPRO",
        "sector": "fx",
        "tick_size": 0.00001,
        "point_value": 10.0,
        "session_id": "fx_24_5",
        "provider_meta": {},
        "expiry": "",
    },
)


# ---------------------------------------------------------------------------
# Tests: always-on DB path (SHADOW-03 graduated — no feature flag)
# ---------------------------------------------------------------------------


class TestGetActiveContractsAlwaysOn:
    """get_active_contracts() always queries the DB — no feature flag."""

    def setup_method(self):
        _reset_cache()

    def test_returns_list_of_instruments(self):
        """Must return list[Instrument], not list[str]."""
        mock_settings = _make_settings()
        conn = _make_mock_db_conn([("ESM6", "ES", "CME")], [_EURUSD_NF_ROW])
        with patch("psycopg.connect", return_value=conn):
            result = get_active_contracts(mock_settings)
        assert isinstance(result, list)
        assert len(result) > 0
        for item in result:
            assert isinstance(item, Instrument), f"Expected Instrument, got {type(item)}"

    def test_always_queries_db(self):
        """DB must always be queried (one connect, three queries on one cursor)."""
        mock_settings = _make_settings()
        conn = _make_mock_db_conn([], [])
        with patch("psycopg.connect", return_value=conn) as mock_connect:
            get_active_contracts(mock_settings)
        assert mock_connect.call_count == 1

    def test_db_error_returns_empty_when_cache_cold(self):
        """On DB error with cold cache, must return empty list (not s.contracts)."""
        mock_settings = _make_settings()
        with patch("psycopg.connect", side_effect=Exception("DB connection refused")):
            result = get_active_contracts(mock_settings)
        assert result == []

    def test_get_active_symbols_returns_strings(self):
        """get_active_symbols() convenience wrapper must return list[str]."""
        mock_settings = _make_settings()
        conn = _make_mock_db_conn([("ESM6", "ES", "CME")], [_EURUSD_NF_ROW])
        with patch("psycopg.connect", return_value=conn):
            result = get_active_symbols(mock_settings)
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, str), f"Expected str, got {type(item)}"

    def test_get_active_symbols_matches_instrument_symbols(self):
        """get_active_symbols() must return the same symbol strings as get_active_contracts()."""
        mock_settings = _make_settings()
        conn1 = _make_mock_db_conn([("ESM6", "ES", "CME")], [_EURUSD_NF_ROW])
        conn2 = _make_mock_db_conn([("ESM6", "ES", "CME")], [_EURUSD_NF_ROW])
        with patch("psycopg.connect", return_value=conn1):
            instruments = get_active_contracts(mock_settings)
        _reset_cache()
        with patch("psycopg.connect", return_value=conn2):
            symbols = get_active_symbols(mock_settings)
        assert symbols == [i.symbol for i in instruments]


# ---------------------------------------------------------------------------
# Tests: DB returns rows
# ---------------------------------------------------------------------------


class TestGetActiveContractsDbEnabled:
    def setup_method(self):
        _reset_cache()

    def test_returns_list_of_instruments_from_db(self):
        """With DB working, must return list[Instrument]."""
        mock_settings = _make_settings()
        conn = _make_mock_db_conn([("ESM6", "ES", "CME")], [_EURUSD_NF_ROW])
        with patch("psycopg.connect", return_value=conn):
            result = get_active_contracts(mock_settings)
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, Instrument)

    def test_db_instrument_inherits_config_defaults(self):
        """DB-sourced futures Instrument must have exchange/point_value/tick_size
        inherited from config-file contracts (not empty defaults)."""
        mock_settings = _make_settings()
        conn = _make_mock_db_conn([("ESM6", "ES", "CME")], [])
        with patch("psycopg.connect", return_value=conn):
            result = get_active_contracts(mock_settings)
        futures = [i for i in result if i.asset_class == AssetClass.FUTURES]
        assert len(futures) >= 1
        es = next((i for i in futures if i.base == "ES" or i.symbol == "ESM6"), None)
        assert es is not None
        assert es.exchange != "", "exchange must be inherited from config"
        assert es.point_value != 0, "point_value must be inherited from config"
        assert es.tick_size != 0, "tick_size must be inherited from config"
        assert es.session_id != "", "session_id must be inherited from config"

    def test_non_futures_from_instruments_table(self):
        """Non-futures Instruments (FX, equity) must come from instruments DB table."""
        mock_settings = _make_settings()
        conn = _make_mock_db_conn([("ESM6", "ES", "CME")], [_EURUSD_NF_ROW])
        with patch("psycopg.connect", return_value=conn):
            result = get_active_contracts(mock_settings)
        fx = [i for i in result if i.asset_class == AssetClass.FX]
        assert len(fx) >= 1, "FX instruments from instruments table must be included"
        assert fx[0].symbol == "EURUSD"

    def test_queries_is_front_month(self):
        """The futures DB query must filter by is_front_month = true."""
        mock_settings = _make_settings()
        conn = _make_mock_db_conn([], [])
        with patch("psycopg.connect", return_value=conn):
            get_active_contracts(mock_settings)
        # Single connection, single cursor: second execute() call is the futures query
        cursor = conn.cursor.return_value.__enter__.return_value
        executed_sql = cursor.execute.call_args_list[1][0][0]
        assert (
            "is_front_month" in executed_sql
        ), f"DB query must filter by is_front_month; got SQL: {executed_sql!r}"

    def test_non_futures_query_filters_asset_class(self):
        """The instruments query must exclude futures rows."""
        mock_settings = _make_settings()
        conn = _make_mock_db_conn([], [])
        with patch("psycopg.connect", return_value=conn):
            get_active_contracts(mock_settings)
        # Single connection, single cursor: third execute() call is the non-futures query
        cursor = conn.cursor.return_value.__enter__.return_value
        executed_sql = cursor.execute.call_args_list[2][0][0]
        assert (
            "FROM instruments" in executed_sql
        ), f"Expected FROM instruments; got: {executed_sql!r}"
        assert "is_active" in executed_sql, f"Expected is_active filter; got: {executed_sql!r}"


# ---------------------------------------------------------------------------
# Tests: DB error fallback
# ---------------------------------------------------------------------------


class TestGetActiveContractsDbFallback:
    def setup_method(self):
        _reset_cache()

    def test_db_error_returns_empty_when_cache_cold(self):
        """On DB connection error with cold cache, must return empty list."""
        mock_settings = _make_settings()
        with patch("psycopg.connect", side_effect=Exception("DB connection refused")):
            result = get_active_contracts(mock_settings)
        assert isinstance(result, list)
        assert result == [], "Cold-start DB error must return empty list, not s.contracts"

    def test_db_error_returns_cache_when_warm(self):
        """On DB error with a warm cache, must return the cached instruments."""
        import src.config.settings as settings_mod

        mock_settings = _make_settings()
        # Pre-warm the cache
        conn = _make_mock_db_conn([("ESM6", "ES", "CME")], [_EURUSD_NF_ROW])
        with patch("psycopg.connect", return_value=conn):
            cached = get_active_contracts(mock_settings)
        assert len(cached) > 0

        # Expire TTL so the next call re-queries — but now DB is down
        settings_mod._active_contracts_last_refresh = 0.0
        with patch("psycopg.connect", side_effect=Exception("DB down")):
            result = get_active_contracts(mock_settings)
        assert result == cached, "Warm-cache fallback must return cached instruments"


# ---------------------------------------------------------------------------
# Tests: cache behaviour
# ---------------------------------------------------------------------------


class TestGetActiveContractsCache:
    def setup_method(self):
        _reset_cache()

    def test_second_call_within_60s_uses_cache(self):
        """Second call within 60 seconds must return cached result without DB query."""
        mock_settings = _make_settings()
        conn = _make_mock_db_conn([("ESM6", "ES", "CME")], [_EURUSD_NF_ROW])
        with patch("psycopg.connect", return_value=conn) as mock_connect:
            result1 = get_active_contracts(mock_settings)
            result2 = get_active_contracts(mock_settings)
        # One connect call on first query; zero on second (cached)
        assert (
            mock_connect.call_count == 1
        ), f"DB must only be queried on first call within cache TTL, called {mock_connect.call_count} times"
        assert result1 == result2

    def test_cache_expires_after_60s(self):
        """After forcing cache expiry, next call must re-query the DB."""
        import src.config.settings as settings_mod

        mock_settings = _make_settings()
        conn1 = _make_mock_db_conn([("ESM6", "ES", "CME")], [_EURUSD_NF_ROW])
        conn2 = _make_mock_db_conn([("ESM6", "ES", "CME")], [_EURUSD_NF_ROW])
        with patch("psycopg.connect", side_effect=[conn1, conn2]) as mock_connect:
            get_active_contracts(mock_settings)
            call_count_after_first = mock_connect.call_count
            settings_mod._active_contracts_last_refresh = time.monotonic() - 61.0
            get_active_contracts(mock_settings)
            call_count_after_second = mock_connect.call_count
        assert call_count_after_first == 1, "First query: 1 connect call (shared connection)"
        assert call_count_after_second == 2, "DB must be re-queried after cache expires (2 total)"


# ---------------------------------------------------------------------------
# Tests: return type is always list[Instrument]
# ---------------------------------------------------------------------------


class TestGetActiveContractsReturnType:
    def setup_method(self):
        _reset_cache()

    def test_not_list_of_str(self):
        """get_active_contracts() must NOT return list[str]."""
        mock_settings = _make_settings()
        conn = _make_mock_db_conn([("ESM6", "ES", "CME")], [_EURUSD_NF_ROW])
        with patch("psycopg.connect", return_value=conn):
            result = get_active_contracts(mock_settings)
        if result:
            assert not isinstance(
                result[0], str
            ), "get_active_contracts() must return list[Instrument], not list[str]"

    def test_get_active_symbols_returns_list_of_str(self):
        """get_active_symbols() must return list[str]."""
        mock_settings = _make_settings()
        conn = _make_mock_db_conn([("ESM6", "ES", "CME")], [_EURUSD_NF_ROW])
        with patch("psycopg.connect", return_value=conn):
            result = get_active_symbols(mock_settings)
        assert isinstance(result, list)
        if result:
            assert isinstance(result[0], str)

    def test_get_active_symbols_function_exists(self):
        """get_active_symbols must be importable from src.config.settings."""
        from src.config.settings import get_active_symbols as _fn

        assert callable(_fn)
