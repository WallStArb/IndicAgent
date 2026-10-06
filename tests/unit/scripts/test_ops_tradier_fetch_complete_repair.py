"""The one-time Tradier fetch_complete repair (scripts/ops/bars/ops_tradier_fetch_complete_repair.py).

Fakes only (todo 494): no database connection. Contract: the repair set is active equities Tradier
owns with tradeable 1d bars and no 1d fetch_complete; every write goes through
mark_fetch_complete, the flag's one writer, from the earliest accepted load's requested start;
the default run writes nothing and commits nothing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import scripts.ops.bars.ops_tradier_fetch_complete_repair as repair_mod
from scripts.infrastructure.backfill import infrastructure_run_historical_pipeline as pipeline
from scripts.infrastructure.backfill.infrastructure_run_tradier_daily import TRADIER_OWNED_SQL

_CANDIDATES = [("AAA", date(2000, 1, 1)), ("BBB", date(2005, 3, 4))]


class _Cursor:
    def __init__(self, conn: _Conn) -> None:
        self.conn = conn
        self._rows: list[tuple] = []

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.conn.executed.append((sql, params))
        if sql is repair_mod.COUNTS_SQL:
            self._rows = [self.conn.count_rows.pop(0)]
        elif sql is repair_mod.CANDIDATES_SQL:
            self._rows = list(_CANDIDATES)

    def fetchone(self) -> tuple:
        return self._rows[0]

    def fetchall(self) -> list[tuple]:
        return self._rows


class _Conn:
    def __init__(self) -> None:
        self.executed: list[tuple[str, Any]] = []
        self.count_rows = [(979, 2, 0), (981, 0, 0)]
        self.commits = 0

    def __enter__(self) -> _Conn:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def commit(self) -> None:
        self.commits += 1


def _install(monkeypatch: Any) -> _Conn:
    conn = _Conn()
    monkeypatch.setattr(repair_mod.psycopg, "connect", lambda _url: conn)
    monkeypatch.setattr(
        repair_mod, "get_settings", lambda: type("S", (), {"database_url": "postgresql://x"})()
    )
    return conn


def _marks(conn: _Conn) -> list[Any]:
    return [params for sql, params in conn.executed if sql is pipeline._MARK_FETCH_COMPLETE_SQL]


def test_candidate_set_is_tradier_owned_active_equities_with_bars_and_no_flag():
    sql = repair_mod.CANDIDATES_SQL
    assert TRADIER_OWNED_SQL.format(col="i.symbol") in sql
    assert "i.is_active AND i.contract_details->>'asset_class' = 'equity'" in sql
    assert "FROM market_data_ohlcv_tradeable m" in sql
    assert "b.tf = '1d' AND b.fetch_complete" in sql and "NOT EXISTS" in sql
    assert "min(l.requested_start)" in sql and "l.outcome = 'loaded'" in sql


def test_repair_dry_run_writes_nothing(monkeypatch, capsys):
    conn = _install(monkeypatch)
    assert repair_mod.main([]) == 0
    assert _marks(conn) == [] and conn.commits == 0
    out = capsys.readouterr().out
    assert "owned_unflagged_with_bars': 2" in out and "candidates: 2: AAA BBB" in out


def test_apply_runs_the_one_writer_per_name_and_commits_once(monkeypatch, capsys):
    conn = _install(monkeypatch)
    assert repair_mod.main(["--apply"]) == 0
    assert _marks(conn) == [
        {"symbol": "AAA", "tf": "1d", "since": datetime(2000, 1, 1, tzinfo=UTC)},
        {"symbol": "BBB", "tf": "1d", "since": datetime(2005, 3, 4, tzinfo=UTC)},
    ]
    assert conn.commits == 1
    out = capsys.readouterr().out
    assert "marked: 2" in out and "after: {'flagged': 981" in out


def test_repair_uses_the_pipeline_writer_itself():
    assert repair_mod.mark_fetch_complete is pipeline.mark_fetch_complete
