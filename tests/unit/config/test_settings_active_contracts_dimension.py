"""Tests for get_active_contracts()'s dimension parameter (Phase 174 Plan 06, D-07a/D-07b).

get_active_contracts() gained a `dimension` parameter ("backfill" | "compute" | "live") that
selects which WHERE clause narrows the non-futures instruments query, and the module-level
cache was converted from a single list/float to per-dimension dicts so a cached result for one
dimension can never be served to a caller asking for another (T-174-16).

Covers: default-equivalence (case 1), per-dimension narrowing (case 2), live-is-empty (case 3),
invalid dimension (case 4), cache isolation (case 5), cache hit (case 6), invalidation
(case 7), dimension-scoped error path (case 8), and concurrent cross-dimension contention
(case 9). No test opens a real psycopg connection.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from structlog.testing import capture_logs

import src.config.settings as settings_mod
from src.config.settings import get_active_contracts

# ---------------------------------------------------------------------------
# Fake psycopg connection/cursor — same one-connection-three-queries shape as
# tests/unit/services/test_service_contract_resolution.py's _make_mock_db_conn,
# extended to select query-3's rows by inspecting the executed SQL's dimension
# clause rather than a fixed fetchall() side_effect list.
# ---------------------------------------------------------------------------


def _make_settings() -> MagicMock:
    mock = MagicMock()
    mock.database_url = "postgresql://postgres:postgres@localhost:5432/indicagent"
    return mock


def _nf_row(symbol: str) -> tuple:
    """Build a non-futures instruments row: (symbol, base, contract_details dict)."""
    return (
        symbol,
        symbol,
        {
            "symbol": symbol,
            "base": symbol,
            "name": f"{symbol} equity",
            "asset_class": "equity",
            "exchange": "SMART",
            "sector": "equity",
            "tick_size": 0.01,
            "point_value": 1.0,
            "session_id": "nyse",
            "provider_meta": {},
            "expiry": "",
        },
    )


class _FakeCursor:
    """Fake psycopg cursor for get_active_contracts()'s 3 sequential execute()/fetchall() calls.

    Query 3's (non-futures) returned rows are selected by inspecting the executed SQL for the
    dimension clause, mirroring how the real WHERE clause filters server-side — so a caller
    asking for one dimension is structurally guaranteed to receive that dimension's fake rows.
    """

    def __init__(
        self,
        recorder: list[str],
        rows_by_dimension: dict[str, list[tuple]],
        delay: float = 0.0,
    ) -> None:
        self.recorder = recorder
        self.rows_by_dimension = rows_by_dimension
        self.delay = delay
        self._last_sql = ""

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str, *args: object, **kwargs: object) -> None:
        self._last_sql = sql
        self.recorder.append(sql)

    def fetchall(self) -> list[tuple]:
        sql = self._last_sql
        if "FROM contract_metadata" in sql:
            return []
        if "asset_class' = 'futures'" in sql:
            return []
        if "live_tradeable = true" in sql:
            dimension = "live"
        elif "compute_eligible = true" in sql:
            dimension = "compute"
        elif "is_active = true" in sql:
            dimension = "backfill"
        else:
            return []
        if self.delay:
            time.sleep(self.delay)
        return self.rows_by_dimension.get(dimension, [])


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def cursor(self) -> _FakeCursor:
        return self._cursor


@pytest.fixture(autouse=True)
def _reset_cache():
    """Clear both per-dimension cache dicts under the lock before and after each test."""
    with settings_mod._settings_lock:
        settings_mod._active_contracts_cache.clear()
        settings_mod._active_contracts_last_refresh.clear()
    yield
    with settings_mod._settings_lock:
        settings_mod._active_contracts_cache.clear()
        settings_mod._active_contracts_last_refresh.clear()


# ---------------------------------------------------------------------------
# Case 1: default-equivalence (D-07a, RESEARCH.md Assumption A5)
# ---------------------------------------------------------------------------


def test_default_equivalence_matches_backfill_and_uses_compute_eligible_clause():
    """Unparameterized call == dimension='backfill' when every row is compute_eligible=true."""
    mock_settings = _make_settings()
    rows = [_nf_row("AAA"), _nf_row("BBB")]
    recorder: list[str] = []

    def _connect(_dsn):
        return _FakeConnection(_FakeCursor(recorder, {"backfill": rows, "compute": rows}))

    with patch("psycopg.connect", side_effect=_connect):
        default_result = get_active_contracts(mock_settings)

    with settings_mod._settings_lock:
        settings_mod._active_contracts_cache.clear()
        settings_mod._active_contracts_last_refresh.clear()

    with patch("psycopg.connect", side_effect=_connect):
        backfill_result = get_active_contracts(mock_settings, dimension="backfill")

    default_symbols = {i.symbol for i in default_result}
    backfill_symbols = {i.symbol for i in backfill_result}
    assert default_symbols == backfill_symbols == {"AAA", "BBB"}

    default_sql = [
        sql for sql in recorder if "FROM instruments" in sql and "compute_eligible = true" in sql
    ]
    assert (
        default_sql
    ), f"Expected default call's SQL to filter on compute_eligible=true: {recorder}"


# ---------------------------------------------------------------------------
# Case 2: compute narrows correctly
# ---------------------------------------------------------------------------


def test_compute_excludes_ineligible_symbol_backfill_includes_it():
    mock_settings = _make_settings()
    recorder: list[str] = []
    rows_by_dimension = {
        "backfill": [_nf_row("ELIGIBLE"), _nf_row("INELIGIBLE")],
        "compute": [_nf_row("ELIGIBLE")],
    }

    def _connect(_dsn):
        return _FakeConnection(_FakeCursor(recorder, rows_by_dimension))

    with patch("psycopg.connect", side_effect=_connect):
        backfill_result = get_active_contracts(mock_settings, dimension="backfill")

    with settings_mod._settings_lock:
        settings_mod._active_contracts_cache.clear()
        settings_mod._active_contracts_last_refresh.clear()

    with patch("psycopg.connect", side_effect=_connect):
        compute_result = get_active_contracts(mock_settings, dimension="compute")

    backfill_symbols = {i.symbol for i in backfill_result}
    compute_symbols = {i.symbol for i in compute_result}
    assert backfill_symbols == {"ELIGIBLE", "INELIGIBLE"}
    assert compute_symbols == {"ELIGIBLE"}
    assert "INELIGIBLE" not in compute_symbols


# ---------------------------------------------------------------------------
# Case 3: live is empty by design (D-07b)
# ---------------------------------------------------------------------------


def test_live_dimension_empty_and_sql_has_all_three_predicates():
    mock_settings = _make_settings()
    recorder: list[str] = []
    rows_by_dimension: dict[str, list[tuple]] = {"live": []}

    def _connect(_dsn):
        return _FakeConnection(_FakeCursor(recorder, rows_by_dimension))

    with patch("psycopg.connect", side_effect=_connect):
        result = get_active_contracts(mock_settings, dimension="live")

    assert result == []
    live_sql = [sql for sql in recorder if "live_tradeable = true" in sql]
    assert live_sql, f"Expected a query with the live_tradeable clause: {recorder}"
    sql = live_sql[0]
    assert "is_active = true" in sql
    assert "compute_eligible = true" in sql
    assert "live_tradeable = true" in sql


# ---------------------------------------------------------------------------
# Case 4: invalid dimension raises
# ---------------------------------------------------------------------------


def test_invalid_dimension_raises_before_any_db_query():
    mock_connect = MagicMock()
    with patch("psycopg.connect", mock_connect):
        with pytest.raises(ValueError) as excinfo:
            get_active_contracts(dimension="bogus")
    message = str(excinfo.value)
    assert "bogus" in message
    for option in ("backfill", "compute", "live"):
        assert option in message
    assert mock_connect.call_count == 0, "invalid dimension must not reach the DB at all"


# ---------------------------------------------------------------------------
# Case 5: cache isolation
# ---------------------------------------------------------------------------


def test_cache_isolation_live_then_compute_issues_second_query():
    mock_settings = _make_settings()
    recorder: list[str] = []
    rows_by_dimension = {"live": [], "compute": [_nf_row("FULLSET1"), _nf_row("FULLSET2")]}

    def _connect(_dsn):
        return _FakeConnection(_FakeCursor(recorder, rows_by_dimension))

    with patch("psycopg.connect", side_effect=_connect) as mock_connect:
        live_result = get_active_contracts(mock_settings, dimension="live")
        compute_result = get_active_contracts(mock_settings, dimension="compute")

    assert live_result == []
    assert {i.symbol for i in compute_result} == {"FULLSET1", "FULLSET2"}
    assert (
        mock_connect.call_count == 2
    ), "compute call must issue its own DB query, not reuse live's cached empty list"


# ---------------------------------------------------------------------------
# Case 6: cache hit within TTL
# ---------------------------------------------------------------------------


def test_cache_hit_within_ttl_issues_one_query():
    mock_settings = _make_settings()
    recorder: list[str] = []
    rows_by_dimension = {"compute": [_nf_row("X")]}

    def _connect(_dsn):
        return _FakeConnection(_FakeCursor(recorder, rows_by_dimension))

    with patch("psycopg.connect", side_effect=_connect) as mock_connect:
        result1 = get_active_contracts(mock_settings)
        result2 = get_active_contracts(mock_settings)

    assert mock_connect.call_count == 1
    assert {i.symbol for i in result1} == {i.symbol for i in result2} == {"X"}


# ---------------------------------------------------------------------------
# Case 7: invalidation clears all dimensions
# ---------------------------------------------------------------------------


def test_invalidation_clears_all_dimensions():
    mock_settings = _make_settings()
    recorder: list[str] = []
    rows_by_dimension = {
        "compute": [_nf_row("C1")],
        "backfill": [_nf_row("B1"), _nf_row("B2")],
    }

    def _connect(_dsn):
        return _FakeConnection(_FakeCursor(recorder, rows_by_dimension))

    with patch("psycopg.connect", side_effect=_connect) as mock_connect:
        get_active_contracts(mock_settings, dimension="compute")
        get_active_contracts(mock_settings, dimension="backfill")
        assert mock_connect.call_count == 2

        settings_mod.invalidate_active_contracts_cache()

        get_active_contracts(mock_settings, dimension="compute")
        get_active_contracts(mock_settings, dimension="backfill")
        assert (
            mock_connect.call_count == 4
        ), "invalidation must force re-query for every previously-warm dimension"


# ---------------------------------------------------------------------------
# Case 8: cold-start error path is dimension-scoped
# ---------------------------------------------------------------------------


def test_error_path_falls_back_to_warm_dimension_only_and_logs_dimension():
    mock_settings = _make_settings()
    recorder: list[str] = []
    rows_by_dimension = {"compute": [_nf_row("WARM1")]}

    def _connect(_dsn):
        return _FakeConnection(_FakeCursor(recorder, rows_by_dimension))

    with patch("psycopg.connect", side_effect=_connect):
        warm_compute = get_active_contracts(mock_settings, dimension="compute")
    assert len(warm_compute) == 1

    with patch("psycopg.connect", side_effect=Exception("DB down")):
        compute_result = get_active_contracts(mock_settings, dimension="compute")
        assert compute_result == warm_compute, "warm compute cache must be returned on DB error"

        with capture_logs() as cap_logs:
            live_result = get_active_contracts(mock_settings, dimension="live")

    assert live_result == [], "cold live dimension must return [], never compute's warm list"
    critical_events = [
        e for e in cap_logs if e["event"] == "get_active_contracts.cold_start_db_unavailable"
    ]
    assert critical_events, f"expected cold_start_db_unavailable event, got {cap_logs}"
    assert critical_events[0]["dimension"] == "live"


# ---------------------------------------------------------------------------
# Case 9: concurrent cross-dimension calls do not corrupt or cross-contaminate the cache
# ---------------------------------------------------------------------------


def test_concurrent_cross_dimension_calls_no_cross_contamination():
    mock_settings = _make_settings()
    recorder: list[str] = []
    rows_by_dimension = {
        "backfill": [_nf_row("BACKFILL_SYM")],
        "compute": [_nf_row("COMPUTE_SYM")],
        "live": [_nf_row("LIVE_SYM")],
    }
    expected_symbols = {
        "backfill": {"BACKFILL_SYM"},
        "compute": {"COMPUTE_SYM"},
        "live": {"LIVE_SYM"},
    }

    def _connect(_dsn):
        # Fresh cursor per connect() call with a short sleep inside the dimension-scoped
        # fetchall() to force real interleaving under _settings_lock across threads.
        return _FakeConnection(_FakeCursor(recorder, rows_by_dimension, delay=0.01))

    dimensions_cycle = (["backfill", "compute", "live"] * 3)[:8]
    results: dict[int, tuple[str, set[str]]] = {}
    errors: list[Exception] = []
    results_lock = threading.Lock()

    def _worker(idx: int, dimension: str) -> None:
        try:
            instruments = get_active_contracts(mock_settings, dimension=dimension)
            symbols = {i.symbol for i in instruments}
            with results_lock:
                results[idx] = (dimension, symbols)
        except Exception as error:  # noqa: BLE001 -- test must observe, not swallow, any escape
            with results_lock:
                errors.append(error)

    with patch("psycopg.connect", side_effect=_connect):
        threads = [
            threading.Thread(target=_worker, args=(idx, dimension))
            for idx, dimension in enumerate(dimensions_cycle)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

    assert not errors, f"Threads raised exceptions: {errors}"
    assert len(results) == len(dimensions_cycle), "every thread must have recorded a result"
    for idx, (dimension, symbols) in results.items():
        assert (
            symbols == expected_symbols[dimension]
        ), f"thread {idx} asked for dimension={dimension!r} but got symbols={symbols}"

    with settings_mod._settings_lock:
        cache_keys = set(settings_mod._active_contracts_cache.keys())
        refresh_keys = set(settings_mod._active_contracts_last_refresh.keys())
        assert cache_keys == {"backfill", "compute", "live"}, cache_keys
        assert refresh_keys == {"backfill", "compute", "live"}, refresh_keys
        for dimension in ("backfill", "compute", "live"):
            cached_symbols = {i.symbol for i in settings_mod._active_contracts_cache[dimension]}
            assert (
                cached_symbols == expected_symbols[dimension]
            ), f"cache[{dimension!r}] holds {cached_symbols}, expected {expected_symbols[dimension]}"
