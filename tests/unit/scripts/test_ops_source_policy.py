"""ops_source_policy.py: row writes, open-row refusal, --add/--close/--plan modes (185-38).

The Tradier admission sweep went with its subject (plan 191-25). Fakes only (todo 494): no
database.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime

import pytest

from scripts.ops.bars import ops_source_policy as policy


class _FakeConn:
    """insert_row's connection: overlapping rows refuse, others insert (records the args)."""

    def __init__(self, open_symbols: set[str]) -> None:
        self.open_symbols = open_symbols
        self.inserted: list[tuple] = []

    class _Txn:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    def transaction(self):
        return self._Txn()

    async def fetchval(self, sql, *args):
        return args[1] if args[1] in self.open_symbols else None

    async def execute(self, sql, *args):
        self.inserted.append(args)


def test_insert_refuses_a_row_overlapping_an_open_symbol_row():
    record = {
        "timeframe": "1d",
        "symbol": "X",
        "valid_from": date(2010, 1, 1),
        "valid_to": None,
        "ingress_mode": "observed",
        "primary_source": "ibkr",
        "fallback_source": None,
        "reason": "basis run",
        "evidence": {"n_common": 300},
    }
    conn = _FakeConn({"X"})
    assert asyncio.run(policy.insert_row(conn, record)) is False and conn.inserted == []
    conn = _FakeConn(set())
    assert asyncio.run(policy.insert_row(conn, record)) is True
    (args,) = conn.inserted
    assert args[0] == "1d" and args[1] == "X" and args[4] == "observed"
    assert args[5] == "ibkr" and args[6] is None
    assert json.loads(args[8])["n_common"] == 300


def test_add_requires_evidence():
    with pytest.raises(SystemExit):
        policy.main(
            [
                "--add",
                "--symbol",
                "REX",
                "--valid-from",
                "2004-01-01",
                "--primary",
                "ibkr",
                "--reason",
                "basis run",
            ]
        )


def test_add_refuses_an_empty_evidence_object():
    with pytest.raises(SystemExit):
        policy.main(
            [
                "--add",
                "--symbol",
                "REX",
                "--valid-from",
                "2004-01-01",
                "--primary",
                "ibkr",
                "--reason",
                "basis run",
                "--evidence",
                "{}",
            ]
        )


class _CliConn:
    """Records every statement; the --close UPDATE reports `closed` rows (185-37 Task 1)."""

    vendors = ("ibkr", "alpaca", "tradier", "derived")

    def __init__(self, closed: int = 1) -> None:
        self.statements: list[str] = []
        self.closed = closed

    class _Txn:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    def transaction(self):
        return self._Txn()

    async def fetchval(self, sql, *args):
        self.statements.append(sql)
        return None

    async def fetch(self, sql, *args):
        assert "controlled_vocabulary" in sql and "bar_vendor" in sql
        return [{"code": c} for c in self.vendors]

    async def execute(self, sql, *args):
        self.statements.append(sql)
        return f"UPDATE {self.closed}" if sql.lstrip().startswith("UPDATE") else "INSERT 0 1"

    async def close(self):
        return None


def _run_cli(monkeypatch, conn: _CliConn, argv: list[str]) -> int:
    class _Settings:
        database_url = "postgresql+asyncpg://fake/fake"

    async def _connect(dsn):
        return conn

    monkeypatch.setattr(policy, "Settings", _Settings)
    monkeypatch.setattr(policy.asyncpg, "connect", _connect)
    return policy.main(argv)


_ADD = [
    "--add",
    "--symbol",
    "RJF",
    "--valid-from",
    "2006-01-03",
    "--valid-to",
    "2010-01-04",
    "--primary",
    "ibkr",
    "--reason",
    "basis run",
    "--evidence",
    '{"run": {"start": "2006-01-03"}}',
]


def test_add_dry_run_prints_the_row_and_writes_nothing(monkeypatch, capsys):
    conn = _CliConn()
    assert _run_cli(monkeypatch, conn, _ADD) == 0
    assert conn.statements == []
    assert "dry run: would insert" in capsys.readouterr().out


def test_add_apply_inserts_one_row_with_the_database_recorded_at(monkeypatch):
    conn = _CliConn()
    assert _run_cli(monkeypatch, conn, [*_ADD, "--apply"]) == 0
    inserts = [s for s in conn.statements if "INSERT INTO bar_source_policy" in s]
    assert len(inserts) == 1
    # recorded_at is the column default now(); the CLI never supplies it.
    assert "recorded_at" not in inserts[0]


_CLOSE = [
    "--close",
    "--symbol",
    "RJF",
    "--valid-to",
    "2026-10-07",
    "--reason",
    "rollback",
]


def test_close_dry_run_writes_nothing(monkeypatch):
    conn = _CliConn()
    assert _run_cli(monkeypatch, conn, _CLOSE) == 0
    assert conn.statements == []


def test_close_targets_only_the_open_row_and_refuses_when_none_is_open(monkeypatch):
    assert "valid_to IS NULL" in policy._CLOSE_POLICY_SQL
    conn = _CliConn(closed=1)
    assert _run_cli(monkeypatch, conn, [*_CLOSE, "--apply"]) == 0
    conn = _CliConn(closed=0)  # the name's row is already closed
    assert _run_cli(monkeypatch, conn, [*_CLOSE, "--apply"]) == 2


_RETIRE = [
    "--retire",
    "--symbol",
    "QRVO",
    "--valid-from",
    "2016-01-04",
    "--reason",
    "todo 566 3c",
    "--evidence",
    '{"ibkr_head": null}',
]


class _RetireConn(_CliConn):
    """--retire: the live-row lookup answers `row`; the retire UPDATE reports `retired` rows."""

    def __init__(self, row: dict | None, retired: int = 1) -> None:
        super().__init__(closed=retired)
        self.row = row
        self.lookups: list[tuple] = []
        self.writes: list[tuple] = []

    async def fetchrow(self, sql, *args):
        assert "FROM bar_source_policy_current" in sql  # a retired row is never found again
        self.lookups.append(args)
        return self.row

    async def execute(self, sql, *args):
        self.writes.append(args)
        return await super().execute(sql, *args)


_LIVE_ROW = {"policy_id": "ac4a8b7b", "primary_source": "ibkr", "fallback_source": None}


def test_retire_dry_run_finds_the_row_and_writes_nothing(monkeypatch):
    conn = _RetireConn(_LIVE_ROW)
    assert _run_cli(monkeypatch, conn, _RETIRE) == 0
    assert conn.lookups == [("QRVO", date(2016, 1, 4))] and conn.statements == []


def test_retire_apply_retires_the_row_with_reason_and_evidence_in_one_statement(monkeypatch):
    conn = _RetireConn(_LIVE_ROW)
    assert _run_cli(monkeypatch, conn, [*_RETIRE, "--apply"]) == 0
    assert conn.statements == [policy._RETIRE_SYMBOL_ROW_SQL]
    assert conn.writes == [
        ("QRVO", date(2016, 1, 4), 'todo 566 3c | evidence: {"ibkr_head": null}')
    ]
    sql = policy._RETIRE_SYMBOL_ROW_SQL
    assert "retired_at IS NULL" in sql and "timeframe = '1d'" in sql


@pytest.mark.parametrize("row, retired", [(None, 1), (_LIVE_ROW, 0)])
def test_retire_refuses_a_missing_or_concurrently_retired_row(monkeypatch, row, retired):
    conn = _RetireConn(row, retired=retired)
    assert _run_cli(monkeypatch, conn, [*_RETIRE, "--apply"]) == 2


@pytest.mark.parametrize(
    "extra, message",
    [
        (["--timeframe", "5m"], "1d only"),
        (["--timeframe", "1h"], "1d only"),
        (["--valid-to", "2026-10-03"], "takes no"),
        (["--reselect"], "takes no"),
        (["--evidence", "{}"], "non-empty JSON"),
        (["--evidence", "{ibkr_head: null}"], "not JSON"),
        (["--symbols", "MKC"], "takes no"),
    ],
)
def test_retire_refuses_before_connecting(extra, message):
    with pytest.raises(SystemExit, match=message):
        policy.main([*_RETIRE, *extra])


def test_retire_refuses_a_bad_date_and_an_incomplete_command():
    bad = [*_RETIRE]
    bad[bad.index("2016-01-04")] = "2016-1-4"
    with pytest.raises(SystemExit, match="--valid-from"):
        policy.main(bad)
    with pytest.raises(SystemExit, match="--retire needs"):
        policy.main(["--retire", "--symbol", "QRVO"])


_ALPACA_SPAN = [
    "--add",
    "--timeframe",
    "5m",
    "--symbol",
    "AAPL",
    "--valid-from",
    "2099-01-02",  # forward: a backdated direct span needs --reselect (tests below)
    "--primary",
    "alpaca",
    "--reason",
    "reproduces canonical",
    "--evidence",
    '{"n": 1}',
]


def test_vendor_choices_come_from_the_cvr_not_a_hardcoded_list(monkeypatch, capsys):
    conn = _CliConn()
    assert _run_cli(monkeypatch, conn, _ALPACA_SPAN) == 0  # alpaca is a bar_vendor code
    assert "dry run: would insert" in capsys.readouterr().out
    assert conn.statements == []
    conn = _CliConn()
    conn.vendors = ("ibkr",)  # the same call against a vocabulary without alpaca is refused
    with pytest.raises(SystemExit, match=r"unknown vendor 'alpaca'.*ibkr"):
        _run_cli(monkeypatch, conn, _ALPACA_SPAN)


def test_unknown_fallback_vendor_is_refused_with_the_valid_list(monkeypatch):
    conn = _CliConn()
    with pytest.raises(SystemExit, match="valid bar_vendor codes: ibkr, alpaca"):
        _run_cli(monkeypatch, conn, [*_ALPACA_SPAN, "--fallback", "databento"])


def test_five_minute_span_inserts_with_direct_ingress_mode(monkeypatch):
    conn = _CliConn()
    assert _run_cli(monkeypatch, conn, [*_ALPACA_SPAN, "--apply"]) == 0
    assert any("INSERT INTO bar_source_policy" in s for s in conn.statements)


def test_ingress_mode_follows_the_timeframe():
    rows = {
        tf: policy.INGRESS_MODE.get(tf, policy.DEFAULT_INGRESS_MODE) for tf in policy.TIMEFRAMES
    }
    assert rows == {
        "1d": "observed",
        "5m": "direct",
        "1m": "direct",
        "15m": "derived",
        "1h": "derived",
        "4h": "direct",
    }


class _SpanConn(_FakeConn):
    """Records the full bind arguments of a span insert; overlap only for symbols in `open_symbols`."""

    async def fetchval(self, sql, timeframe, symbol, valid_from, valid_to):
        return 1 if symbol in self.open_symbols else None


def test_second_span_of_a_name_is_allowed_when_it_overlaps_nothing():
    row = {
        "timeframe": "5m",
        "symbol": "AAPL",
        "valid_from": date(2016, 1, 1),
        "valid_to": date(2020, 1, 1),
        "primary_source": "alpaca",
        "fallback_source": "ibkr",
        "reason": "r",
        "evidence": {"n": 1},
    }
    conn = _SpanConn(set())
    assert asyncio.run(policy.insert_row(conn, row)) is True
    assert conn.inserted[0][0] == "5m" and conn.inserted[0][4] == "direct"
    assert asyncio.run(policy.insert_row(_SpanConn({"AAPL"}), row)) is False


# --- backdated direct-timeframe rows (191-07 review finding 6) ------------------------------

_BACKDATED = [*_ALPACA_SPAN[:6], "2016-01-01", *_ALPACA_SPAN[7:]]


def test_a_backdated_direct_span_is_refused_without_reselect(monkeypatch, capsys):
    conn = _CliConn()
    assert _run_cli(monkeypatch, conn, [*_BACKDATED, "--apply"]) == 2
    assert "needs --reselect" in capsys.readouterr().out and conn.statements == []
    # 1d rows are the daily rule's: the admission sweep's backdated rows stay allowed
    assert _run_cli(monkeypatch, _CliConn(), [*_ADD, "--apply"]) == 0


def test_closing_a_direct_span_in_the_past_is_refused_without_reselect(monkeypatch):
    close_5m = [*_CLOSE, "--timeframe", "5m", "--apply"]
    conn = _CliConn()
    assert _run_cli(monkeypatch, conn, close_5m) == 2 and conn.statements == []


def test_backdated_is_only_for_direct_timeframes_before_today():
    today = date(2026, 10, 14)
    assert policy.backdated("5m", date(2026, 10, 13), today)
    assert not policy.backdated("5m", today, today)
    assert not policy.backdated("1d", date(2006, 1, 3), today)
    assert policy.session_today(datetime(2026, 10, 15, 2, 0, tzinfo=UTC)) == date(2026, 10, 14)


class _PgCursor:
    def __init__(self, overlap=None, rowcount=1):
        self.executed: list[tuple[str, tuple]] = []
        self.overlap, self.rowcount = overlap, rowcount

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self.overlap


class _PgConn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self):
        return self.cur


def _reselect(monkeypatch, cur, mode, row):
    seen = {}

    class _Params:
        policy_rows = ("p",)
        kind_order = {"named": 1}

        class write:  # noqa: N801 - mirrors RawContractParams.write
            batch_rows = 7

    monkeypatch.setattr(policy, "read_raw_params", lambda c: _Params)

    def _select(conn, **kw):
        seen.update(kw)
        return "result"

    monkeypatch.setattr(policy, "select_and_write", _select)
    return policy.write_and_reselect(_PgConn(cur), mode=mode, row=row), seen


def test_reselect_writes_the_span_and_re_selects_its_window_in_one_transaction(monkeypatch):
    row = {
        "timeframe": "5m",
        "symbol": "AAPL",
        "valid_from": date(2026, 3, 10),
        "valid_to": date(2026, 8, 1),
        "primary_source": "alpaca",
        "fallback_source": "ibkr",
        "reason": "r",
        "evidence": {"n": 1},
    }
    cur = _PgCursor()
    result, seen = _reselect(monkeypatch, cur, "add", row)
    assert result == "result"
    assert any("INSERT INTO bar_source_policy" in sql for sql, _ in cur.executed)
    assert seen["symbols"] == ["AAPL"] and seen["timeframe"] == "5m" and seen["batch_rows"] == 7
    assert seen["start"] == datetime(2026, 3, 10, 4, 0, tzinfo=UTC)  # 00:00 EDT
    assert seen["end"] == datetime(2026, 8, 1, 4, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="overlapping"):
        _reselect(monkeypatch, _PgCursor(overlap=(1,)), "add", row)


def test_reselect_of_a_close_re_selects_from_valid_to_on(monkeypatch):
    row = {"timeframe": "5m", "symbol": "AAPL", "valid_to": date(2026, 1, 5)}
    cur = _PgCursor()
    _result, seen = _reselect(monkeypatch, cur, "close", row)
    # the series' selection lock comes before the policy write (second review, low item)
    assert cur.executed[0] == (policy._SELECTION_LOCK_SQL, ("bar_selection|AAPL|5m",))
    assert "UPDATE bar_source_policy" in cur.executed[1][0]
    assert seen["start"] == datetime(2026, 1, 5, 5, 0, tzinfo=UTC)  # 00:00 EST
    assert seen["end"] == policy._FAR_FUTURE
    with pytest.raises(ValueError, match="open rows closed"):
        _reselect(monkeypatch, _PgCursor(rowcount=0), "close", row)
