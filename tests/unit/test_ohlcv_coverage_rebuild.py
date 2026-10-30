"""Coverage rebuild and 1d refresh are per source over ohlcv_raw (phase 191 plan 06).

Pure SQL-shape tests on a recording cursor; the live-DB behavior is
tests/integration/test_ohlcv_coverage_atomic_write.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from services.ohlcv_coverage_writer import (
    FETCH_STATUSES,
    REBUILD_PROVIDERS,
    count_new_slots,
    fetch_status_for_outcome,
    rebuild_from_stored_state,
    refresh_1d_bounds,
)


class _Cursor:
    rowcount = 1

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def execute(self, sql: str, params: object = None) -> None:
        self.calls.append((sql, params))


def test_rebuild_reads_only_the_providers_vendor_rows_of_raw():
    cur = _Cursor()
    rebuild_from_stored_state(cur, ["AAA"], provider="ibkr")
    (sql, params), _zero = cur.calls
    assert "FROM ohlcv_raw" in sql
    assert "vendor = %(provider)s" in sql
    assert "count(DISTINCT" in sql
    for old in ("ohlcv_intraday_raw_archive", "market_data_ohlcv"):
        assert old not in sql
    assert params == {"provider": "ibkr", "symbols": ["AAA"], "not_coverage": ["smart_adjusted"]}
    # 1d counts only the kinds that cover a session, the same set the planner uses
    assert "NOT (timeframe = '1d' AND kind = ANY(%(not_coverage)s))" in sql


def test_rebuild_with_no_provider_runs_every_provider_once_in_order():
    cur = _Cursor()
    assert rebuild_from_stored_state(cur) == 2 * len(REBUILD_PROVIDERS)  # upsert + zeroing each
    upserts = [(sql, p) for sql, p in cur.calls if sql.lstrip().startswith("INSERT")]
    assert [p["provider"] for _, p in upserts] == list(REBUILD_PROVIDERS)
    assert set(REBUILD_PROVIDERS) == {"ibkr", "alpaca"}


def test_rebuild_scoped_to_no_symbols_issues_no_sql():
    cur = _Cursor()
    assert rebuild_from_stored_state(cur, []) == 0
    assert cur.calls == []


def test_each_providers_status_comes_from_its_own_requests_only():
    cur = _Cursor()
    rebuild_from_stored_state(cur)
    by_provider = {p["provider"]: sql for sql, p in cur.calls if sql.lstrip().startswith("INSERT")}
    assert "source = 'ibkr'" in by_provider["ibkr"]
    assert "source = 'alpaca'" in by_provider["alpaca"]
    assert "source = 'alpaca'" not in by_provider["ibkr"]


def test_unknown_provider_raises_before_any_sql():
    cur = _Cursor()
    with pytest.raises(ValueError, match="unknown coverage provider"):
        rebuild_from_stored_state(cur, ["AAA"], provider="tradier")
    assert cur.calls == []


def test_refresh_1d_reads_the_providers_raw_rows_of_every_kind():
    cur = _Cursor()
    refresh_1d_bounds(cur, ["B", "A", "A"], provider="ibkr")
    (sql, params), _zero = cur.calls
    assert "FROM ohlcv_raw" in sql and "vendor = %s" in sql
    # a slot counts once whatever its covering kinds; the adjusted series is not one
    assert "kind <> ALL(%s)" in sql
    assert "market_data_ohlcv" not in sql
    assert params == ("ibkr", "ibkr", ["smart_adjusted"], ["A", "B"])


def test_rebuild_zeroes_a_provider_row_that_has_no_raw_row_of_its_own():
    cur = _Cursor()
    rebuild_from_stored_state(cur, ["AAA"], provider="ibkr")
    _upsert, (sql, params) = cur.calls
    assert sql.lstrip().startswith("UPDATE ohlcv_coverage")
    assert "SET earliest_timestamp = NULL, latest_timestamp = NULL, row_count = 0" in sql
    assert "c.provider = %(provider)s" in sql
    assert "NOT EXISTS" in sql and "m.vendor = c.provider" in sql
    # status, counter and last_fetched_at describe the fetcher's outcomes: never touched here
    for untouched in ("last_fetch_status", "consecutive_failures", "last_fetched_at"):
        assert untouched not in sql
    assert params == {"provider": "ibkr", "symbols": ["AAA"], "not_coverage": ["smart_adjusted"]}


def test_unscoped_rebuild_zeroes_across_every_series_of_the_provider():
    cur = _Cursor()
    rebuild_from_stored_state(cur, provider="alpaca")
    _upsert, (sql, params) = cur.calls
    assert "symbol = ANY" not in sql
    assert params == {"provider": "alpaca", "not_coverage": ["smart_adjusted"]}


def test_refresh_1d_zeroes_a_symbol_the_provider_holds_no_1d_raw_for():
    cur = _Cursor()
    refresh_1d_bounds(cur, ["QRVO"], provider="ibkr")
    _refresh, (sql, params) = cur.calls
    assert "c.timeframe = '1d'" in sql and "NOT EXISTS" in sql
    assert params == {"provider": "ibkr", "symbols": ["QRVO"], "not_coverage": ["smart_adjusted"]}


class _HeldCursor(_Cursor):
    def __init__(self, held: list[tuple[datetime, int]]) -> None:
        super().__init__()
        self._held = held

    def fetchall(self) -> list[tuple[datetime, int]]:
        return self._held


_S0 = datetime(2025, 6, 2, 13, 30, tzinfo=UTC)
_S1 = datetime(2025, 6, 2, 13, 35, tzinfo=UTC)


def test_a_stamp_the_provider_held_under_another_kind_adds_no_slot():
    # _S0 was held before (one row now beside the new one); _S1 is new in both rows and stamp
    cur = _HeldCursor([(_S0, 2), (_S1, 1)])
    assert count_new_slots(cur, "AAA", "5m", "alpaca", [_S0, _S1]) == 1
    ((sql, params),) = cur.calls
    assert "vendor = %s" in sql and params[:3] == ("AAA", "5m", "alpaca")


def test_two_kinds_new_at_one_stamp_make_one_slot():
    cur = _HeldCursor([(_S0, 2)])
    assert count_new_slots(cur, "AAA", "5m", "alpaca", [_S0, _S0]) == 1


def test_no_new_rows_issue_no_sql():
    cur = _HeldCursor([])
    assert count_new_slots(cur, "AAA", "5m", "alpaca", []) == 0
    assert cur.calls == []


def test_outcome_status_is_the_one_mapping_the_rebuild_is_generated_from():
    cur = _Cursor()
    rebuild_from_stored_state(cur, ["AAA"], provider="alpaca")
    sql = cur.calls[0][0]
    assert (
        "CASE outcome WHEN 'bars' THEN 'ok' WHEN 'no_data' THEN 'no_data' "
        "WHEN 'timeout' THEN 'error' WHEN 'failed' THEN 'error' END" in sql
    )
    assert "outcome IN ('bars', 'no_data', 'timeout', 'failed')" in sql
    assert fetch_status_for_outcome("bars") == "ok"
    assert fetch_status_for_outcome("no_data") == "no_data"
    assert fetch_status_for_outcome("timeout") == fetch_status_for_outcome("failed") == "error"
    assert fetch_status_for_outcome("skipped") is None  # the rebuild ignores it too
    assert {"ok", "no_data", "error"} == set(FETCH_STATUSES)


def test_a_stored_stamp_that_is_not_a_chunk_key_raises_instead_of_counting_zero():
    naive = _S0.replace(tzinfo=None)
    with pytest.raises(KeyError):
        count_new_slots(_HeldCursor([(naive, 1)]), "AAA", "5m", "alpaca", [_S0])
