"""The one-time 1d lineage, digest and legacy-flag repair (plan 185-30).

Fakes only (todo 494): no test opens a database connection or writes D1. A fake asyncpg
connection records every statement and answers the script's reads from in-memory tables; the
batch helpers and write_1d_digests are replaced on the module.

Contract: the lineage upsert and the unmatched check are the loader's own statements and the
digest writer is bar_derivation's (no copied SQL); the default is a dry run that writes nothing;
--apply runs one stage-tradier batch with one transaction per name under bar_derivation_writer;
unmatched bars are reported and fail the batch while other names complete; digests use
tradier-v1 for owned names and d2-v1 otherwise; the legacy retirement touches timeframe 1d only.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import Any

import pytest

import scripts.infrastructure.backfill.infrastructure_run_tradier_daily as loader
import scripts.ops.bars.ops_tradier_lineage_backfill as ops
import services.bar_derivation as bar_derivation
from src.intelligence.bars.derivation import RULE_VERSION
from src.intelligence.bars.sources import TRADIER_RULE_VERSION

_BATCH_ID = "44444444-4444-4444-4444-444444444444"
_TS = datetime(2007, 4, 2, tzinfo=UTC)
_TS2 = datetime(2008, 9, 19, tzinfo=UTC)


class _Tx:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    async def start(self) -> None:
        self.conn.events.append(("begin",))

    async def commit(self) -> None:
        self.conn.events.append(("commit",))

    async def rollback(self) -> None:
        self.conn.events.append(("rollback",))
        self.conn.role = None

    async def __aenter__(self) -> _Tx:
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type is None:
            await self.commit()
        else:
            await self.rollback()
        self.conn.role = None


class FakeConn:
    """asyncpg.Connection-shaped recorder; reads are answered from in-memory tables."""

    def __init__(
        self,
        *,
        owned: list[str] = (),
        canonical: list[tuple[str, bool]] = (),
        status: dict[str, tuple[int, int, int]] | None = None,
        unmatched: dict[str, list[Any]] | None = None,
        lineage_rows: dict[str, int] | None = None,
        legacy_candidates: list[dict[str, Any]] = (),
        flags: list[dict[str, Any]] = (),
        fail_symbols: tuple[str, ...] = (),
    ) -> None:
        self.owned = list(owned)
        self.canonical = list(canonical)
        self.status = status or {}
        self.unmatched = unmatched or {}
        self.lineage_rows = lineage_rows or {}
        self.legacy_candidates = list(legacy_candidates)
        self.flags = [dict(f) for f in flags]
        self.fail_symbols = fail_symbols
        self.events: list[tuple] = []
        self.role: str | None = None

    def transaction(self) -> _Tx:
        return _Tx(self)

    async def execute(self, sql: str, *args: Any) -> str:
        self.events.append(("execute", sql, args, self.role))
        if sql.strip().startswith("SET LOCAL ROLE"):
            self.role = sql.split()[-1]
            return "SET"
        if sql is loader.TRADIER_LINEAGE_UPSERT_SQL:
            if args[0] in self.fail_symbols:
                raise RuntimeError(f"boom {args[0]}")
            return f"INSERT 0 {self.lineage_rows.get(args[0], 0)}"
        if sql is ops.RETIRE_LEGACY_FLAG_SQL:
            symbol, ts = args
            one_d_only = re.search(r"timeframe\s*=\s*'1d'", sql) is not None
            keep, gone = [], 0
            for f in self.flags:
                hit = (
                    f["symbol"] == symbol
                    and f["timestamp"] == ts
                    and f["rule"] == "legacy_price_sanity_status"
                    and (f["timeframe"] == "1d" or not one_d_only)
                )
                if hit:
                    gone += 1
                else:
                    keep.append(f)
            self.flags = keep
            return f"DELETE {gone}"
        raise AssertionError(f"unexpected execute: {sql[:80]}")

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        self.events.append(("fetch", sql, args, self.role))
        if sql is ops.OWNED_SYMBOLS_SQL:
            return [{"symbol": s} for s in self.owned]
        if sql is ops.CANONICAL_1D_SYMBOLS_SQL:
            return [{"symbol": s, "owned": o} for s, o in self.canonical]
        if sql is loader._TRADIER_LINEAGE_UNMATCHED_SQL:
            return [{"bar_date": d} for d in self.unmatched.get(args[0], [])]
        if sql is ops.REPLACED_LEGACY_FLAGS_SQL:
            return list(self.legacy_candidates)
        raise AssertionError(f"unexpected fetch: {sql[:80]}")

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, int]:
        self.events.append(("fetchrow", sql, args, self.role))
        if sql is ops.LINEAGE_STATUS_SQL:
            n_stored, n_needs, n_stale = self.status.get(args[0], (0, 0, 0))
            return {"n_stored": n_stored, "n_needs": n_needs, "n_stale_d2": n_stale}
        raise AssertionError(f"unexpected fetchrow: {sql[:80]}")

    def executed(self, sql: str) -> list[tuple]:
        return [e for e in self.events if e[0] == "execute" and e[1] is sql]


@pytest.fixture
def batches(monkeypatch):
    record: dict[str, Any] = {"opened": [], "closed": []}

    async def fake_open(conn, *, stage, rule_version, apr_snapshot, n_symbols, detail=None):
        record["opened"].append(
            {"stage": stage, "rule_version": rule_version, "n_symbols": n_symbols, "detail": detail}
        )
        return _BATCH_ID

    async def fake_close(conn, batch_id, *, status, detail=None):
        record["closed"].append({"batch_id": batch_id, "status": status, "detail": detail})

    monkeypatch.setattr(ops, "open_batch", fake_open)
    monkeypatch.setattr(ops, "close_batch", fake_close)
    return record


@pytest.fixture
def digests(monkeypatch):
    calls: list[dict[str, Any]] = []
    stale: dict[str, int] = {}

    async def fake_write(conn, *, symbol, batch_id, rule_version):
        # The digest writer opens its own transaction (a savepoint inside a dry run's).
        calls.append(
            {
                "symbol": symbol,
                "batch_id": batch_id,
                "rule_version": rule_version,
                "events_before": len(conn.events),
            }
        )
        return stale.get(symbol, 0)

    monkeypatch.setattr(ops, "write_1d_digests", fake_write)
    return calls, stale


def _run(conn: FakeConn, **kwargs: Any) -> int:
    defaults = {
        "symbols": None,
        "lineage": False,
        "digests": False,
        "retire": False,
        "apply": False,
    }
    defaults.update(kwargs)
    return asyncio.run(ops.run(conn, **defaults))


# --- statement identity (no copied SQL) -----------------------------------------------------


def test_statements_are_imported_not_copied():
    assert ops.TRADIER_LINEAGE_UPSERT_SQL is loader.TRADIER_LINEAGE_UPSERT_SQL
    assert ops._TRADIER_LINEAGE_UNMATCHED_SQL is loader._TRADIER_LINEAGE_UNMATCHED_SQL
    assert ops.TRADIER_OWNED_SQL is loader.TRADIER_OWNED_SQL
    assert ops.write_1d_digests is bar_derivation.write_1d_digests
    source = open(ops.__file__).read()
    assert "INSERT INTO canonical_bar_lineage" not in source
    assert "INSERT INTO bar_content_digest" not in source


# --- lineage --------------------------------------------------------------------------------


def test_lineage_dry_run_reports_and_writes_nothing(batches, capsys):
    conn = FakeConn(
        owned=["AAA", "BBB"],
        status={"AAA": (100, 40, 30), "BBB": (50, 0, 0)},
        unmatched={"BBB": [datetime(2010, 1, 4).date()]},
    )
    rc = _run(conn, lineage=True)
    out = capsys.readouterr().out
    # an unmatched bar is a finding in a dry run too
    assert rc == 1
    assert batches["opened"] == [] and batches["closed"] == []
    assert not [e for e in conn.events if e[0] == "execute"]
    assert "AAA" in out and "40" in out
    assert "unmatched" in out and "BBB" in out
    assert "stored 150" in out and "needs_lineage 40" in out and "stale_d2 30" in out


def test_lineage_apply_one_batch_role_first_per_name(batches, digests):
    conn = FakeConn(owned=["AAA", "BBB"], lineage_rows={"AAA": 7, "BBB": 3})
    rc = _run(conn, lineage=True, apply=True)
    assert rc == 0
    assert len(batches["opened"]) == 1
    opened = batches["opened"][0]
    assert opened["stage"] == "tradier" and opened["rule_version"] == TRADIER_RULE_VERSION
    upserts = conn.executed(loader.TRADIER_LINEAGE_UPSERT_SQL)
    assert [u[2] for u in upserts] == [("AAA", _BATCH_ID), ("BBB", _BATCH_ID)]
    # every upsert runs under the writer role, inside its own transaction
    assert all(u[3] == "bar_derivation_writer" for u in upserts)
    assert sum(1 for e in conn.events if e[0] == "begin") == 2
    closed = batches["closed"][0]
    assert closed["status"] == "completed"
    assert closed["detail"]["lineage"]["lineage_rows"] == 10


def test_lineage_unmatched_fails_batch_but_other_names_complete(batches, digests):
    d = datetime(2012, 5, 7).date()
    conn = FakeConn(
        owned=["AAA", "BAD", "ZZZ"],
        lineage_rows={"AAA": 5, "BAD": 4, "ZZZ": 2},
        unmatched={"BAD": [d]},
    )
    rc = _run(conn, lineage=True, apply=True)
    assert rc == 1
    upserted = [u[2][0] for u in conn.executed(loader.TRADIER_LINEAGE_UPSERT_SQL)]
    assert upserted == ["AAA", "BAD", "ZZZ"]
    closed = batches["closed"][0]
    assert closed["status"] == "failed"
    assert closed["detail"]["lineage"]["unmatched"] == {"BAD": [str(d)]}


def test_lineage_name_error_rolls_back_that_name_only(batches, digests):
    conn = FakeConn(owned=["AAA", "ERR", "ZZZ"], lineage_rows={"AAA": 1, "ZZZ": 1})
    conn.fail_symbols = ("ERR",)
    rc = _run(conn, lineage=True, apply=True)
    assert rc == 1
    assert ("rollback",) in conn.events
    assert batches["closed"][0]["status"] == "failed"
    assert "ERR" in batches["closed"][0]["detail"]["failures"][0]
    assert batches["closed"][0]["detail"]["lineage"]["lineage_rows"] == 2


def test_symbols_override_selection(batches):
    conn = FakeConn(owned=["AAA", "BBB"])
    _run(conn, lineage=True, symbols=["ZZZ"])
    assert [e[2] for e in conn.events if e[0] == "fetchrow"] == [("ZZZ",)]
    assert not [e for e in conn.events if e[0] == "fetch" and e[1] is ops.OWNED_SYMBOLS_SQL]


# --- digests --------------------------------------------------------------------------------


def test_digest_dry_run_rolls_back_and_counts_stale(batches, digests, capsys):
    calls, stale = digests
    stale.update({"AAA": 3, "IBK": 2})
    conn = FakeConn(canonical=[("AAA", True), ("IBK", False), ("OK", True)])
    rc = _run(conn, digests=True)
    assert rc == 0
    assert batches["opened"] == []
    assert {c["symbol"]: c["rule_version"] for c in calls} == {
        "AAA": TRADIER_RULE_VERSION,
        "IBK": RULE_VERSION,
        "OK": TRADIER_RULE_VERSION,
    }
    # each dry-run digest is inside a transaction that is rolled back, never committed
    assert [e[0] for e in conn.events if e[0] in ("begin", "commit", "rollback")] == [
        "begin",
        "rollback",
    ] * 3
    out = capsys.readouterr().out
    assert "stale_months 5" in out


def test_digest_apply_records_ibkr_owned_in_batch_detail(batches, digests):
    calls, stale = digests
    stale.update({"AAA": 3, "IBK": 2})
    conn = FakeConn(canonical=[("AAA", True), ("IBK", False)])
    rc = _run(conn, digests=True, apply=True)
    assert rc == 0
    assert all(c["batch_id"] == _BATCH_ID for c in calls)
    detail = batches["closed"][0]["detail"]["digests"]
    assert detail["tradier_owned"] == {"n_symbols": 1, "rows": 3, "rule_version": "tradier-v1"}
    assert detail["ibkr_owned"]["rows"] == 2
    assert detail["ibkr_owned"]["rule_version"] == RULE_VERSION
    assert detail["ibkr_owned"]["symbols"] == {"IBK": 2}


# --- legacy flag retirement -----------------------------------------------------------------


def _candidate(symbol: str, ts: datetime) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "timestamp": ts,
        "detail": {"price_sanity_status": "confirmed_corrupt"},
        "stored_source": "tradier",
        "owned": True,
        "replaced": [
            {
                "load_id": "l1",
                "old_open": 1.0,
                "old_high": 2.0,
                "old_low": 0.5,
                "old_close": 1.5,
                "old_volume": 10,
                "old_source": "ibkr_named",
            }
        ],
    }


def test_retire_statements_scope_to_1d():
    where = ops.RETIRE_LEGACY_FLAG_SQL.split("WHERE", 1)[1]
    assert re.search(r"timeframe\s*=\s*'1d'", where)
    assert "rule = 'legacy_price_sanity_status'" in where
    cand = ops.REPLACED_LEGACY_FLAGS_SQL
    assert re.search(r"f\.timeframe\s*=\s*'1d'", cand)
    assert "old_source = ANY($1" in cand
    assert "m.source <> ALL($1" in cand


def test_retire_dry_run_lists_and_deletes_nothing(batches, digests, capsys):
    flags = [
        {"symbol": "SPY", "timeframe": "1d", "timestamp": _TS, "rule": ops.LEGACY_RULE},
    ]
    conn = FakeConn(legacy_candidates=[_candidate("SPY", _TS)], flags=flags)
    rc = _run(conn, retire=True)
    assert rc == 0
    assert conn.flags == flags
    assert "SPY" in capsys.readouterr().out
    assert batches["opened"] == []


def test_retire_apply_leaves_intraday_legacy_flags(batches, digests):
    calls, _ = digests
    flags = [
        {"symbol": "SPY", "timeframe": "1d", "timestamp": _TS, "rule": ops.LEGACY_RULE},
        # an intraday legacy flag on the same key must survive
        {"symbol": "SPY", "timeframe": "1h", "timestamp": _TS, "rule": ops.LEGACY_RULE},
        {"symbol": "XRT", "timeframe": "1d", "timestamp": _TS2, "rule": ops.LEGACY_RULE},
        {"symbol": "XRT", "timeframe": "1d", "timestamp": _TS2, "rule": "vol_scaled_jump"},
    ]
    conn = FakeConn(
        legacy_candidates=[_candidate("SPY", _TS), _candidate("XRT", _TS2)], flags=flags
    )
    rc = _run(conn, retire=True, apply=True)
    assert rc == 0
    left = {(f["symbol"], f["timeframe"], f["rule"]) for f in conn.flags}
    assert left == {("SPY", "1h", ops.LEGACY_RULE), ("XRT", "1d", "vol_scaled_jump")}
    # the delete runs under the scrub's writer role, after the candidate read
    deletes = conn.executed(ops.RETIRE_LEGACY_FLAG_SQL)
    assert all(d[3] == "bar_derivation_writer" for d in deletes)
    read = next(e for e in conn.events if e[0] == "fetch" and e[1] is ops.REPLACED_LEGACY_FLAGS_SQL)
    assert read[3] is None
    retired = batches["closed"][0]["detail"]["retired_legacy_flags"]
    assert [(r["symbol"], r["timestamp"]) for r in retired] == [
        ("SPY", _TS.isoformat()),
        ("XRT", _TS2.isoformat()),
    ]
    assert retired[0]["replaced"][0]["old_close"] == 1.5
    assert retired[0]["detail"] == {"price_sanity_status": "confirmed_corrupt"}
    # the retired names are re-digested in the same batch
    assert sorted(c["symbol"] for c in calls) == ["SPY", "XRT"]


def test_retire_mismatched_delete_count_rolls_back(batches, digests):
    # a candidate whose flag is already gone: the delete count disagrees, nothing commits
    conn = FakeConn(legacy_candidates=[_candidate("SPY", _TS)], flags=[])
    rc = _run(conn, retire=True, apply=True)
    assert rc == 1
    assert ("rollback",) in conn.events
    assert batches["closed"][0]["status"] == "failed"
