"""ops_source_policy.py: admission sweep actions, exception rows, open-row refusal (185-38).

Fakes only (todo 494): no database.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta

import pytest

from scripts.ops.bars import ops_source_policy as policy
from src.intelligence.bars.derivation import Observation

_PARAMS = policy.SweepParams(min_overlap=60, min_agree_share=0.9, tolerance_bp=10.0)
_T = datetime(2026, 10, 1, tzinfo=UTC)
_FIRST = date(2010, 1, 1)


def _obs(route: str, day: date, close: float) -> Observation:
    return Observation(
        request_id=f"{route}-{day}",
        route=route,
        bar_date=day,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1,
        fetched_at=_T,
        legacy=False,
        what_to_show="TRADES",
    )


def _series(n: int, ratio_old: float, ratio_recent: float, n_recent: int = 60):
    days = [date(2020, 1, 1) + timedelta(days=i) for i in range(n)]
    obs = []
    for i, d in enumerate(days):
        ratio = ratio_recent if i >= n - n_recent else ratio_old
        obs += [_obs("TRADIER", d, 100.0), _obs("SMART", d, 100.0 * ratio)]
    return obs


def _sweep(obs, incumbent):
    return policy.sweep_symbol(
        "X", obs, [], incumbent=incumbent, first_observation=_FIRST, params=_PARAMS
    )


def test_agreeing_name_is_admitted_with_no_row():
    row = _sweep(_series(300, 1.0, 1.0), incumbent=False)
    assert row.action == policy.ACTION_ADMIT


def test_ibkr_only_failing_name_gets_a_row():
    row = _sweep(_series(300, 6.7, 6.7), incumbent=False)  # CTVA-like
    assert row.action == policy.ACTION_WRITE


def test_ibkr_only_name_with_no_common_session_gets_a_row():
    obs = [_obs("SMART", date(2020, 1, d), 10.0) for d in range(1, 20)]
    row = _sweep(obs, incumbent=False)
    assert row.action == policy.ACTION_WRITE and row.admission.n_common == 0


def test_incumbent_failing_only_in_the_past_is_routed_to_185_37_without_a_row():
    row = _sweep(_series(300, 1.5, 1.0), incumbent=True)  # RJF-like
    assert row.action == policy.ACTION_ROUTE
    with pytest.raises(ValueError):
        policy.exception_row(row, _PARAMS, _T)


def test_incumbent_with_too_few_common_sessions_keeps_tradier_without_a_row():
    # APMD-like: 43 agreeing sessions; ZWS-like: no IBKR SMART answer at all.
    assert _sweep(_series(43, 1.0, 1.0, n_recent=43), incumbent=True).action == policy.ACTION_KEEP
    no_ibkr = [_obs("TRADIER", date(2020, 1, d), 10.0) for d in range(1, 20)]
    assert _sweep(no_ibkr, incumbent=True).action == policy.ACTION_KEEP


def test_incumbent_failing_now_gets_a_row():
    row = _sweep(_series(300, 1.0, 0.53), incumbent=True)  # W-like: a different series now
    # Whole-history agreement 240/300 = 0.8 fails, and the recent window fails too.
    assert row.action == policy.ACTION_WRITE


def test_exception_row_is_ibkr_primary_with_no_fallback_from_first_observation():
    row = _sweep(_series(300, 6.7, 6.7), incumbent=False)
    record = policy.exception_row(row, _PARAMS, _T)
    assert record["valid_from"] == _FIRST and record["valid_to"] is None
    assert record["primary_source"] == "ibkr" and record["fallback_source"] is None
    evidence = record["evidence"]
    assert evidence["n_common"] == 300 and evidence["agree_share"] == 0.0
    assert evidence["median_ratio"] == pytest.approx(6.7)
    assert evidence["min_overlap_sessions"] == 60 and evidence["tolerance_bp"] == 10.0
    assert evidence["plan"] == "185-38"
    json.dumps(evidence)  # JSON-safe
    assert "185-38" in record["reason"]


def test_report_row_has_every_column():
    row = _sweep(_series(300, 6.7, 6.7), incumbent=False).report_row()
    assert tuple(row) == policy._REPORT_COLUMNS
    assert row["action"] == "write" and row["n_common"] == "300"


class _FakeConn:
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

    async def fetchval(self, sql, timeframe, symbol, valid_from, valid_to):
        assert "&&" in sql and timeframe == "1d"
        return 1 if symbol in self.open_symbols else None

    async def execute(self, sql, *args):
        assert "INSERT INTO bar_source_policy" in sql
        self.inserted.append(args)
        return "INSERT 0 1"


def test_insert_refuses_a_row_overlapping_an_open_symbol_row():
    record = policy.exception_row(_sweep(_series(300, 6.7, 6.7), incumbent=False), _PARAMS, _T)
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


def test_the_sweep_is_a_dry_run_by_default():
    import inspect

    source = inspect.getsource(policy.run_sweep)
    assert source.index("if not apply:") < source.index("insert_row(")


def test_sweep_apply_never_rewrites_a_name_that_already_has_a_symbol_row():
    # VMRK's row was closed by decision (routed to 185-37): a later sweep must not re-add it.
    write = _sweep(_series(300, 6.7, 6.7), incumbent=False)
    admit = _sweep(_series(300, 1.0, 1.0), incumbent=False)
    assert policy.rows_to_write([write, admit], decided=frozenset({"X"})) == []
    assert policy.rows_to_write([write, admit], decided=frozenset()) == [write]


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


def test_load_first_date_comes_from_the_raw_inputs_not_the_observation_store(monkeypatch) -> None:
    """Plan 191-11: valid_from's first date is the earliest TRADES date among the d2-v2 routes
    in the same raw read (LEGACY_IMPORT included, venue routes and ADJUSTED_LAST excluded)."""

    class _Obs:
        def __init__(self, route: str, day: int, what_to_show: str = "TRADES") -> None:
            self.route, self.bar_date, self.what_to_show = route, date(2020, 1, day), what_to_show

    inputs = [
        _Obs("SMART", 9),
        _Obs("LEGACY_IMPORT", 5),
        _Obs("ARCA", 1),
        _Obs("SMART", 2, "ADJUSTED_LAST"),
    ]

    async def _read(conn, symbol):
        return inputs, []

    class _Conn:
        async def fetchval(self, sql, *args):
            assert "ohlcv_observation" not in sql
            return False

    monkeypatch.setattr(policy, "read_daily_inputs", _read)
    _obs, _splits, incumbent, first = asyncio.run(policy._load(_Conn(), "X"))
    assert first == date(2020, 1, 5)
    assert incumbent is False


def test_incumbent_sql_reads_the_tradier_pair_not_a_source_label() -> None:
    """191-15: market_data_ohlcv carries (vendor, kind); the incumbent test must not filter
    a source column that no longer exists."""
    sql = " ".join(policy._INCUMBENT_SQL.split())
    assert "vendor = $2" in sql and "kind = $3" in sql
    assert "source" not in sql
