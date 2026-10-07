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

    async def fetchval(self, sql, symbol):
        assert "valid_to IS NULL" in sql
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
    assert args[0] == "X" and args[3] == "ibkr" and args[4] is None
    assert json.loads(args[6])["n_common"] == 300


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
