"""Tests for get_active_contracts()'s dimension parameter (Phase 174 Plan 06, D-07a/D-07b;
extended by Plan 174-13, D-09, with the "compute_1d" dimension).

get_active_contracts() gained a `dimension` parameter ("backfill" | "compute" | "live" |
"compute_1d") that selects which WHERE clause narrows the non-futures instruments query, and
the module-level cache was converted from a single list/float to per-dimension dicts so a
cached result for one dimension can never be served to a caller asking for another (T-174-16).

Covers: default-equivalence (case 1), per-dimension narrowing (case 2), live-is-empty (case 3),
invalid dimension (case 4), cache isolation (case 5), cache hit (case 6), invalidation
(case 7), dimension-scoped error path (case 8), and concurrent cross-dimension contention
(case 9). No test opens a real psycopg connection.

Plan 174-13 adds: non-regression pin of the three pre-existing WHERE-clause strings (case 10),
compute_1d narrows on the new column (case 11), compute_1d is cache-isolated (case 12),
invalidation clears compute_1d too (case 13), invalid dimension names all four options
(case 14), and a 1d-only symbol structurally cannot reach "compute"/"live" (case 15).
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


def _nf_row(symbol: str, classification: str | None = "Information Technology") -> tuple:
    """Build a non-futures instruments row: (symbol, base, contract_details dict,
    classification sector name). The 4th column is the indicagent_v1 level-2 node name
    selected by current_level_name_sql("instruments") (Phase 182 D-10); None models a
    symbol with no current assignment."""
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
        classification,
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
        elif "compute_eligible_1d = true" in sql:
            # Must be checked before "compute_eligible = true": that substring is NOT
            # present in "compute_eligible_1d = true" (the "_1d" infix breaks the match),
            # but ordering this branch first keeps the dispatch obviously correct rather
            # than relying on that non-overlap.
            dimension = "compute_1d"
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


def test_dimension_is_a_required_keyword():
    """174 review CR-02 follow-up: no default universe. A caller that omits dimension
    fails at the call, rather than silently receiving "compute"."""
    import inspect

    param = inspect.signature(get_active_contracts).parameters["dimension"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        get_active_contracts(_make_settings())


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
        result1 = get_active_contracts(mock_settings, dimension="compute")
        result2 = get_active_contracts(mock_settings, dimension="compute")

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


# ---------------------------------------------------------------------------
# Case 10 (Plan 174-13, D-09): non-regression pin of the three pre-existing WHERE
# clauses -- a future edit to _ACTIVE_CONTRACTS_DIMENSION_CLAUSES must fail here rather
# than silently changing what the 37 pre-existing call sites see (T-174-52).
# ---------------------------------------------------------------------------


def test_pre_existing_dimension_clauses_are_byte_identical():
    assert settings_mod._ACTIVE_CONTRACTS_DIMENSION_CLAUSES["backfill"] == "is_active = true"
    assert (
        settings_mod._ACTIVE_CONTRACTS_DIMENSION_CLAUSES["compute"]
        == "is_active = true AND compute_eligible = true"
    )
    assert (
        settings_mod._ACTIVE_CONTRACTS_DIMENSION_CLAUSES["live"]
        == "is_active = true AND compute_eligible = true AND live_tradeable = true"
    )


# ---------------------------------------------------------------------------
# Case 11 (Plan 174-13, D-09): compute_1d narrows on compute_eligible_1d, and does NOT
# also filter on compute_eligible -- an accidental "AND compute_eligible = true" would
# silently make compute_1d a subset of compute and hide every 1d-only symbol.
# ---------------------------------------------------------------------------


def test_compute_1d_clause_omits_compute_eligible():
    assert (
        settings_mod._ACTIVE_CONTRACTS_DIMENSION_CLAUSES["compute_1d"]
        == "is_active = true AND compute_eligible_1d = true"
    )


def test_compute_1d_narrows_correctly_and_issues_1d_predicate_sql():
    mock_settings = _make_settings()
    recorder: list[str] = []
    rows_by_dimension = {"compute_1d": [_nf_row("ONLY_1D")]}

    def _connect(_dsn):
        return _FakeConnection(_FakeCursor(recorder, rows_by_dimension))

    with patch("psycopg.connect", side_effect=_connect):
        result = get_active_contracts(mock_settings, dimension="compute_1d")

    assert {i.symbol for i in result} == {"ONLY_1D"}
    compute_1d_sql = [sql for sql in recorder if "compute_eligible_1d = true" in sql]
    assert compute_1d_sql, f"Expected a query with the compute_eligible_1d clause: {recorder}"
    sql = compute_1d_sql[0]
    assert "is_active = true" in sql
    assert "compute_eligible_1d = true" in sql
    assert "compute_eligible = true" not in sql, (
        "compute_1d must not also filter on compute_eligible -- that would silently "
        "make it a subset of compute and hide every 1d-only symbol"
    )


# ---------------------------------------------------------------------------
# Case 12 (Plan 174-13, D-09): compute_1d is cache-isolated from the other three
# dimensions, modeled on case 5's live-then-compute isolation.
# ---------------------------------------------------------------------------


def test_compute_1d_is_cache_isolated_from_other_dimensions():
    mock_settings = _make_settings()
    recorder: list[str] = []
    rows_by_dimension = {
        "backfill": [_nf_row("B1")],
        "compute": [_nf_row("C1")],
        "live": [],
        "compute_1d": [_nf_row("D1")],
    }

    def _connect(_dsn):
        return _FakeConnection(_FakeCursor(recorder, rows_by_dimension))

    with patch("psycopg.connect", side_effect=_connect) as mock_connect:
        backfill_result = get_active_contracts(mock_settings, dimension="backfill")
        compute_result = get_active_contracts(mock_settings, dimension="compute")
        live_result = get_active_contracts(mock_settings, dimension="live")
        compute_1d_result = get_active_contracts(mock_settings, dimension="compute_1d")

    assert mock_connect.call_count == 4, "each of the four dimensions must issue its own query"
    assert {i.symbol for i in backfill_result} == {"B1"}
    assert {i.symbol for i in compute_result} == {"C1"}
    assert live_result == []
    assert {i.symbol for i in compute_1d_result} == {"D1"}

    with settings_mod._settings_lock:
        cache_keys = set(settings_mod._active_contracts_cache.keys())
        assert cache_keys == {"backfill", "compute", "live", "compute_1d"}, cache_keys
        distinct_lists = {
            tuple(sorted(i.symbol for i in lst))
            for lst in settings_mod._active_contracts_cache.values()
        }
        assert (
            len(distinct_lists) == 4
        ), f"expected four distinct cached lists, got {distinct_lists}"


# ---------------------------------------------------------------------------
# Case 13 (Plan 174-13, D-09): invalidate_active_contracts_cache() clears compute_1d too.
# ---------------------------------------------------------------------------


def test_invalidation_clears_compute_1d_too():
    mock_settings = _make_settings()
    recorder: list[str] = []
    rows_by_dimension = {"compute_1d": [_nf_row("D1")]}

    def _connect(_dsn):
        return _FakeConnection(_FakeCursor(recorder, rows_by_dimension))

    with patch("psycopg.connect", side_effect=_connect) as mock_connect:
        get_active_contracts(mock_settings, dimension="compute_1d")
        assert mock_connect.call_count == 1

        settings_mod.invalidate_active_contracts_cache()

        get_active_contracts(mock_settings, dimension="compute_1d")
        assert (
            mock_connect.call_count == 2
        ), "invalidation must force re-query for compute_1d as well as the other dimensions"


# ---------------------------------------------------------------------------
# Case 14 (Plan 174-13, D-09): an invalid dimension still raises before any query, now
# with all four valid dimension names in the message.
# ---------------------------------------------------------------------------


def test_invalid_dimension_message_names_all_four_options():
    mock_connect = MagicMock()
    with patch("psycopg.connect", mock_connect):
        with pytest.raises(ValueError) as excinfo:
            get_active_contracts(dimension="bogus")
    message = str(excinfo.value)
    assert "bogus" in message
    for option in ("backfill", "compute", "compute_1d", "live"):
        assert option in message, f"expected {option!r} in error message: {message}"
    assert mock_connect.call_count == 0, "invalid dimension must not reach the DB at all"


# ---------------------------------------------------------------------------
# Case 15 (Plan 174-13, D-09): a 1d-only symbol (is_active=true, compute_eligible=false,
# compute_eligible_1d=true) is structurally unable to reach "compute" or "live", and is
# present in "compute_1d" and "backfill" -- driven through the real
# _ACTIVE_CONTRACTS_DIMENSION_CLAUSES strings, not a hardcoded expectation, so this test
# fails if a future edit changes which columns any clause reads.
# ---------------------------------------------------------------------------


def _clause_matches(clause: str, row_flags: dict[str, bool]) -> bool:
    """Evaluate a "col1 = true AND col2 = true ..." clause against a flag dict.

    Mirrors exactly what Postgres would evaluate for a row with these boolean column
    values -- used so case 15 proves the 1d-only-symbol guarantee against the real
    _ACTIVE_CONTRACTS_DIMENSION_CLAUSES text rather than a re-derived expectation.
    """
    for term in clause.split(" AND "):
        column = term.strip().removesuffix(" = true").strip()
        if not row_flags.get(column, False):
            return False
    return True


def test_1d_only_symbol_cannot_reach_compute_or_live():
    row_flags = {
        "is_active": True,
        "compute_eligible": False,
        "compute_eligible_1d": True,
        "live_tradeable": False,
    }
    expected_membership = {
        dimension: _clause_matches(clause, row_flags)
        for dimension, clause in settings_mod._ACTIVE_CONTRACTS_DIMENSION_CLAUSES.items()
    }
    assert expected_membership == {
        "backfill": True,
        "compute": False,
        "live": False,
        "compute_1d": True,
    }, expected_membership

    mock_settings = _make_settings()
    recorder: list[str] = []
    rows_by_dimension = {
        dimension: ([_nf_row("ONE_DAY_ONLY")] if is_member else [])
        for dimension, is_member in expected_membership.items()
    }

    def _connect(_dsn):
        return _FakeConnection(_FakeCursor(recorder, rows_by_dimension))

    results: dict[str, set[str]] = {}
    for dimension in ("backfill", "compute", "live", "compute_1d"):
        with settings_mod._settings_lock:
            settings_mod._active_contracts_cache.clear()
            settings_mod._active_contracts_last_refresh.clear()
        with patch("psycopg.connect", side_effect=_connect):
            result = get_active_contracts(mock_settings, dimension=dimension)
        results[dimension] = {i.symbol for i in result}

    assert results["backfill"] == {"ONE_DAY_ONLY"}
    assert results["compute_1d"] == {"ONE_DAY_ONLY"}
    assert results["compute"] == set(), "1d-only symbol must be absent from compute"
    assert results["live"] == set(), "1d-only symbol must be absent from live"


@pytest.mark.parametrize("dimension", ["backfill", "compute", "compute_1d", "live"])
def test_front_month_futures_are_scoped_by_the_dimension(dimension):
    """Front-month futures were returned for every dimension, so a roll marking a front
    month would put futures in `live` that nobody whitelisted. The contract_metadata query
    now applies the dimension clause to the base's template row. Verified live in a
    rolled-back transaction: 0 with the ES template inactive, 1 once it is active and
    live-whitelisted, 0 again after deactivation."""
    recorder: list[str] = []

    def _connect(_dsn):
        return _FakeConnection(_FakeCursor(recorder, {dimension: []}))

    with patch("psycopg.connect", side_effect=_connect):
        get_active_contracts(_make_settings(), dimension=dimension)

    (futures_sql,) = [sql for sql in recorder if "FROM contract_metadata" in sql]
    assert settings_mod.dimension_where_clause(dimension, "i") in futures_sql


# ---------------------------------------------------------------------------
# Phase 182 D-10: Instrument.sector comes from the indicagent_v1 classification
# (level-2 node name), never from contract_details->>'sector'.
# ---------------------------------------------------------------------------


def _run_backfill(rows: list[tuple]) -> tuple[list, list[str]]:
    recorder: list[str] = []

    def _connect(_dsn):
        return _FakeConnection(_FakeCursor(recorder, {"backfill": rows}))

    with patch("psycopg.connect", side_effect=_connect):
        result = get_active_contracts(_make_settings(), dimension="backfill")
    return result, recorder


def test_sector_comes_from_classification_not_contract_details():
    result, _ = _run_backfill([_nf_row("SMH", "Information Technology")])
    assert [i.sector for i in result] == ["Information Technology"]


def test_sector_unclassified_when_no_current_assignment():
    result, _ = _run_backfill([_nf_row("SMH", None)])
    assert [i.sector for i in result] == ["indicagent_v1:unclassified"]


def test_fallback_constructor_path_applies_classification_rule():
    """contract_details that Instrument(**cd) rejects (no symbol key) takes the explicit
    fallback constructor, which fills symbol from the row; the same sector rule must
    apply there."""
    classified = _nf_row("AAA", "Financials")
    del classified[2]["symbol"]
    unclassified = _nf_row("BBB", None)
    del unclassified[2]["symbol"]
    result, _ = _run_backfill([classified, unclassified])
    by_symbol = {i.symbol: i.sector for i in result}
    assert by_symbol == {"AAA": "Financials", "BBB": "indicagent_v1:unclassified"}


def test_non_futures_and_template_queries_select_the_classification_fragment():
    from src.config.classification_service import current_level_name_sql

    _, recorder = _run_backfill([_nf_row("SMH")])
    fragment = current_level_name_sql("instruments")
    template_sql = next(q for q in recorder if "asset_class' = 'futures'" in q)
    non_futures_sql = next(q for q in recorder if "asset_class' != 'futures'" in q)
    assert fragment in template_sql
    assert fragment in non_futures_sql
    # The dimension clause itself is unchanged (case 10 pins the clause strings).
    assert settings_mod._ACTIVE_CONTRACTS_DIMENSION_CLAUSES["backfill"] in non_futures_sql
