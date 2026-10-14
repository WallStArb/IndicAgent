"""Coverage rebuild and 1d refresh are per source over ohlcv_raw (phase 191 plan 06).

Pure SQL-shape tests on a recording cursor; the live-DB behavior is
tests/integration/test_ohlcv_coverage_atomic_write.py.
"""

from __future__ import annotations

import pytest

from services.ohlcv_coverage_writer import (
    REBUILD_PROVIDERS,
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
    ((sql, params),) = cur.calls
    assert "FROM ohlcv_raw" in sql
    assert "vendor = %(provider)s" in sql
    assert "count(DISTINCT" in sql
    for old in ("ohlcv_intraday_raw_archive", "market_data_ohlcv"):
        assert old not in sql
    assert params == {"provider": "ibkr", "symbols": ["AAA"]}


def test_rebuild_with_no_provider_runs_every_provider_once_in_order():
    cur = _Cursor()
    assert rebuild_from_stored_state(cur) == len(REBUILD_PROVIDERS)
    assert [p["provider"] for _, p in cur.calls] == list(REBUILD_PROVIDERS)
    assert set(REBUILD_PROVIDERS) == {"ibkr", "alpaca"}


def test_rebuild_scoped_to_no_symbols_issues_no_sql():
    cur = _Cursor()
    assert rebuild_from_stored_state(cur, []) == 0
    assert cur.calls == []


def test_each_providers_status_comes_from_its_own_requests_only():
    cur = _Cursor()
    rebuild_from_stored_state(cur)
    by_provider = {p["provider"]: sql for sql, p in cur.calls}
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
    ((sql, params),) = cur.calls
    assert "FROM ohlcv_raw" in sql and "vendor = %s" in sql
    assert "kind" not in sql  # a slot counts once whatever its kinds
    assert "market_data_ohlcv" not in sql
    assert params == ("ibkr", "ibkr", ["A", "B"])
