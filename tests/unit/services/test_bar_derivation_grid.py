"""Tests for services/bar_derivation.py --stage grid (phase 185 plans 11 and 31).

Fakes only, no DB (todo 494). A fake pool answers the read shapes the grid stage issues
(config_state APR rows, DISTINCT-symbol discovery over tradeable 5m, per-symbol 5m bars,
5m flag rules, the stored 15m/1h rows with their source, the stored grid flags, the current
5m/15m/1h digests, the answered 5m windows, the vendor-removal verify) and records every call in
order.

The contract under test (plan 185-31, data layer integrity design section 4): per symbol, one
transaction reads the stored 15m/1h rows, classifies the derived rows against the stored derived
rows by exact value (src/intelligence/bars/write_contract.py), and writes only what differs:
one ohlcv_load row per grid timeframe; stored vendor rows archived, their differing archive
observations recorded in ohlcv_revision (origin archive_segment), verified by value and only
then deleted; new derived rows inserted; changed rows upserted (ON CONFLICT DO UPDATE, never a
raw UPDATE) after their old values go to ohlcv_revision (origin load); stale derived rows
deleted with their old values recorded; flags and digests written only where they differ. A
revision ratio above threshold.bar_integrity.max_revision_ratio refuses the symbol (outcome
refused, nothing written, the batch fails).

Derived values are checked against direct arithmetic over the same 5m fixture (plan 06's
direct-oracle convention), never against the implementation's own aggregation path.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from services.bar_derivation import BarDerivation
from src.intelligence.bars import gap_plan
from src.intelligence.bars.digest import bar_content_digest, month_ranges
from src.intelligence.bars.sources import GRID_RULE_VERSION, SOURCE_DERIVED_5M

_BATCH_ID = "11111111-1111-1111-1111-111111111111"
# Monday 2024-06-03, regular NYSE session 13:30-20:00 UTC.
_SESSION_OPEN = datetime(2024, 6, 3, 13, 30, tzinfo=UTC)
# Friday 2024-05-31, the session before it (a different calendar month).
_MAY_OPEN = datetime(2024, 5, 31, 13, 30, tzinfo=UTC)
_JUNE = datetime(2024, 6, 1, tzinfo=UTC)
_MAY = datetime(2024, 5, 1, tzinfo=UTC)


def _five_minute_fixture(n: int = 78, open_at: datetime = _SESSION_OPEN) -> list[tuple]:
    """n 5m bars on one full session: wandering prices, distinct volumes."""
    rows: list[tuple] = []
    for i in range(n):
        px = 100.0 + 0.05 * i
        rows.append(
            (
                open_at + timedelta(seconds=300 * i),
                px,
                px + 0.02,
                px - 0.02,
                px + 0.01,
                1000 + i,
                "USD",
            )
        )
    return rows


def _fixture_arrays(rows: list[tuple], drop: frozenset[int] = frozenset()):
    kept = [r for i, r in enumerate(rows) if i not in drop]
    return (
        np.array([int(r[0].timestamp()) for r in kept], dtype=np.int64),
        np.array([r[1] for r in kept], dtype=np.float64),
        np.array([r[2] for r in kept], dtype=np.float64),
        np.array([r[3] for r in kept], dtype=np.float64),
        np.array([r[4] for r in kept], dtype=np.float64),
        np.array([r[5] for r in kept], dtype=np.float64),
    )


def _expected_month_digests(
    rows: list[tuple],
    drop: frozenset[int] = frozenset(),
    rules: dict[int, tuple[str, ...]] | None = None,
):
    """(range_start -> digest) computed directly from the fixture."""
    rules = rules or {}
    ts, o, h, lo, c, v = _fixture_arrays(rows, drop)
    kept_rules = [rules.get(i, ()) for i in range(len(rows)) if i not in drop]
    out: dict[datetime, str] = {}
    for start, end in month_ranges(ts):
        mask = (ts >= int(start.timestamp())) & (ts < int(end.timestamp()))
        out[start] = bar_content_digest(
            ts[mask], o[mask], h[mask], lo[mask], c[mask], v[mask],
            [kept_rules[i] for i in np.flatnonzero(mask)],
        )  # fmt: skip
    return out


class FakeConn:
    """asyncpg.Connection-shaped fake recording every call chronologically."""

    def __init__(
        self,
        *,
        bars: dict[str, list[tuple]],
        flags: dict[str, list[tuple]] | None = None,
        stored_grid: dict[str, list[dict]] | None = None,
        stored_grid_flags: dict[str, list[dict]] | None = None,
        current_digests: dict[str, list[tuple]] | None = None,
        verify_row: dict[str, object] | None = None,
        answered_windows: dict[str, list[tuple[datetime, datetime]]] | None = None,
        answered_since: bool = False,
        apr: dict[str, str] | None = None,
    ) -> None:
        self.bars = bars
        self.flags = flags or {}
        self.stored_grid = stored_grid or {}
        self.stored_grid_flags = stored_grid_flags or {}
        # symbol -> [(timeframe, range_start, digest)]
        self.current_digests = current_digests or {}
        self.verify_row = verify_row
        self.answered_windows = answered_windows or {}
        self.answered_since = answered_since
        self.apr = {"infra.bar_derivation.grid_symbol_batch": "10", **(apr or {})}
        self.calls: list[tuple[str, str]] = []
        self.statements: list[tuple[str, tuple]] = []
        self.executemany_calls: list[tuple[str, list[tuple]]] = []

    class _Txn:
        def __init__(self, outer: FakeConn) -> None:
            self.outer = outer

        async def __aenter__(self) -> None:
            self.outer.calls.append(("<begin>", ""))

        async def __aexit__(self, *exc: object) -> bool:
            self.outer.calls.append(("<commit>" if not exc[0] else "<rollback>", ""))
            return False

    def transaction(self) -> FakeConn._Txn:
        return self._Txn(self)

    def _vendor_rows(self, symbol: str) -> list[dict]:
        return [r for r in self.stored_grid.get(symbol, []) if r["source"] != SOURCE_DERIVED_5M]

    async def fetch(self, sql: str, *args: object) -> list[object]:
        self.calls.append(("fetch", sql))
        symbol = str(args[0]) if args else ""
        if "config_state" in sql:
            return [{"config_key": k, "config_value": v} for k, v in self.apr.items()]
        if "DISTINCT symbol" in sql:
            return [(s,) for s in sorted(self.bars)]
        if "/* stored_grid */" in sql:
            return list(self.stored_grid.get(symbol, []))
        if "/* stored_grid_flags */" in sql:
            return list(self.stored_grid_flags.get(symbol, []))
        if "/* current_grid_digests */" in sql:
            return [
                {"timeframe": tf, "range_start": start, "digest": digest}
                for tf, start, digest in self.current_digests.get(symbol, [])
            ]
        if "market_data_ohlcv_tradeable" in sql:
            return [
                {
                    "timestamp": r[0],
                    "open": r[1],
                    "high": r[2],
                    "low": r[3],
                    "close": r[4],
                    "volume": r[5],
                    "base": r[6],
                }
                for r in self.bars[symbol]
            ]
        if "bar_quality_flag" in sql:
            return [
                {"timestamp": t, "rule": rule, "quarantine": q}
                for t, rule, q in self.flags.get(symbol, [])
            ]
        if "bar_content_digest_current" in sql:
            return [
                {"range_start": start, "digest": digest}
                for tf, start, digest in self.current_digests.get(symbol, [])
                if tf == "5m"
            ]
        if "ohlcv_request" in sql:
            return [
                {"window_start": start, "window_end": end}
                for start, end in self.answered_windows.get(symbol, [])
            ]
        raise AssertionError(f"unexpected fetch: {sql}")

    async def fetchrow(self, sql: str, *args: object) -> object:
        self.calls.append(("fetchrow", sql))
        if "answered_since" in sql:
            return {"answered_since": self.answered_since}
        assert "/* vendor_removal_verify */" in sql, f"unexpected fetchrow: {sql}"
        if self.verify_row is not None:
            return self.verify_row
        return {"n_removable": len(self._vendor_rows(str(args[0]))), "n_unmatched": 0}

    async def fetchval(self, sql: str, *args: object) -> object:
        self.calls.append(("fetchval", sql))
        assert "bar_derivation_batch" in sql, f"unexpected fetchval: {sql}"
        return _BATCH_ID

    async def execute(self, sql: str, *args: object) -> str:
        self.calls.append(("execute", sql))
        self.statements.append((sql, tuple(args)))
        if "/* delete_vendor_rows */" in sql:
            return f"DELETE {len(self._vendor_rows(str(args[0])))}"
        if "/* delete_stale_derived */" in sql:
            return f"DELETE {len(args[2])}"
        if sql.lstrip().startswith("DELETE"):
            return "DELETE 0"
        return "INSERT 0 5"

    async def executemany(self, sql: str, args_seq: object) -> str:
        args = [tuple(a) for a in args_seq]
        self.calls.append(("executemany", sql))
        self.executemany_calls.append((sql, args))
        return f"INSERT {len(args)}"


class FakePool:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    class _Acquire:
        def __init__(self, conn: FakeConn) -> None:
            self.conn = conn

        async def __aenter__(self) -> FakeConn:
            return self.conn

        async def __aexit__(self, *exc: object) -> bool:
            return False

    def acquire(self) -> FakePool._Acquire:
        return self._Acquire(self.conn)


def _run(conn: FakeConn, **overrides: object) -> dict[str, int]:
    """Run the grid stage against the fake pool; returns the outcome totals."""
    writer = BarDerivation(
        "postgresql://unused",
        stage="grid",
        symbols=overrides.pop("symbols", None),
        changed_only=overrides.pop("changed_only", False),
        apply=overrides.pop("apply", True),
    )
    return asyncio.run(writer.execute(FakePool(conn)))


def _many_rows(conn: FakeConn, marker: str, *, exclude: str | None = None) -> list[tuple]:
    rows: list[tuple] = []
    for sql, args in conn.executemany_calls:
        if marker in sql and (exclude is None or exclude not in sql):
            rows.extend(args)
    return rows


def _inserted_bars(conn: FakeConn) -> list[tuple]:
    """Plain INSERTs of new derived rows (never the ON CONFLICT upsert)."""
    return _many_rows(conn, "INSERT INTO market_data_ohlcv", exclude="ON CONFLICT")


def _upserted_bars(conn: FakeConn) -> list[tuple]:
    return [
        row
        for sql, args in conn.executemany_calls
        if "INSERT INTO market_data_ohlcv" in sql and "ON CONFLICT" in sql
        for row in args
    ]


def _loads(conn: FakeConn) -> list[tuple]:
    return [args for sql, args in conn.statements if "INSERT INTO ohlcv_load" in sql]


def _load_counts(conn: FakeConn) -> dict[str, dict[str, object]]:
    """timeframe -> the load row's fields, read by the column list of the statement."""
    out: dict[str, dict[str, object]] = {}
    for sql, args in conn.statements:
        if "INSERT INTO ohlcv_load" not in sql:
            continue
        columns = [c.strip() for c in sql.split("(", 1)[1].split(")", 1)[0].split(",")]
        row = dict(zip(columns, args, strict=True))
        out[str(row["timeframe"])] = row
    return out


def _revisions(conn: FakeConn) -> list[tuple]:
    return _many_rows(conn, "INSERT INTO ohlcv_revision")


def _bar_writes(conn: FakeConn) -> list[str]:
    """Every statement that writes market_data_ohlcv."""
    sqls = [sql for sql, _ in conn.statements] + [sql for sql, _ in conn.executemany_calls]
    return [
        sql
        for sql in sqls
        if "INSERT INTO market_data_ohlcv" in sql
        or "DELETE FROM market_data_ohlcv" in sql
        or "UPDATE market_data_ohlcv" in sql
    ]


def _index(conn: FakeConn, marker: str, kind: str = "execute") -> int:
    for i, (k, sql) in enumerate(conn.calls):
        if k == kind and marker in sql:
            return i
    raise AssertionError(f"no {kind} call containing {marker!r}")


def _stored_from_first_run(fixture: list[tuple], **conn_kwargs: object):
    """Run once on an empty store; return what the next run would read back as stored."""
    conn = FakeConn(bars={"SPY": fixture}, **conn_kwargs)  # type: ignore[arg-type]
    assert _run(conn)["derived"] == 1
    stored = [
        {
            "timeframe": r[2],
            "timestamp": r[0],
            "open": r[3],
            "high": r[4],
            "low": r[5],
            "close": r[6],
            "volume": r[7],
            "source": r[8],
        }
        for r in _inserted_bars(conn)
    ]
    flags = [
        {
            "timeframe": r[1],
            "timestamp": r[2],
            "rule": r[3],
            "rule_version": r[4],
            "detail": json.loads(r[7]),
        }
        for r in _many_rows(conn, "INSERT INTO bar_quality_flag")
    ]
    digests = [(r[1], r[2], r[4]) for r in _many_rows(conn, "INSERT INTO bar_content_digest")]
    return stored, flags, digests


# ---------------------------------------------------------------------------
# First derivation, idempotent second pass, one changed bar, stale rows
# ---------------------------------------------------------------------------


def test_first_derivation_inserts_the_grid_and_records_one_load_per_timeframe():
    fixture = _five_minute_fixture()
    conn = FakeConn(
        bars={"SPY": fixture}, flags={"SPY": [(fixture[5][0], "gap_before_next", False)]}
    )
    totals = _run(conn)
    assert totals["derived"] == 1 and totals["failed"] == 0

    rows_15m = [r for r in _inserted_bars(conn) if r[2] == "15m"]
    rows_1h = [r for r in _inserted_bars(conn) if r[2] == "1h"]
    assert len(rows_15m) == 26 and len(rows_1h) == 7
    assert all(r[8] == SOURCE_DERIVED_5M for r in rows_15m + rows_1h)
    assert not _upserted_bars(conn)

    # Direct-oracle spot values: first 15m bar from fixture bars 0-2, last 1h bar
    # (15:30-16:00 ET, six constituents) from fixture bars 72-77.
    first = rows_15m[0]
    assert first[0] == _SESSION_OPEN
    assert first[3] == 100.0
    assert first[4] == pytest.approx(100.0 + 0.05 * 2 + 0.02)
    assert first[5] == pytest.approx(100.0 - 0.02)
    assert first[6] == pytest.approx(100.0 + 0.05 * 2 + 0.01)
    assert first[7] == 1000 + 1001 + 1002
    last_1h = rows_1h[-1]
    assert last_1h[0] == _SESSION_OPEN + timedelta(hours=6)
    assert last_1h[7] == sum(1000 + i for i in range(72, 78))
    assert sum(r[7] for r in rows_1h) == sum(r[5] for r in fixture)

    loads = _load_counts(conn)
    assert set(loads) == {"15m", "1h"}
    for tf, n in (("15m", 26), ("1h", 7)):
        load = loads[tf]
        assert load["source"] == "derived" and load["outcome"] == "applied"
        assert load["destination"] == "market_data_ohlcv"
        assert load["caller"] == "bar_derivation-grid"
        assert load["batch_id"] == _BATCH_ID
        assert (load["n_bars"], load["n_new"], load["n_changed"]) == (n, n, 0)
        assert (load["n_unchanged"], load["n_removed"]) == (0, 0)
    # Nothing stored: no archive, no vendor delete, no revision.
    assert not any("ohlcv_intraday_raw_archive" in sql for sql, _ in conn.statements)
    assert not _revisions(conn)

    # Order inside the symbol's transaction: stored reads, role, load rows, bars, flags, digests.
    i_read = _index(conn, "/* stored_grid */", kind="fetch")
    i_role = next(
        i for i, (k, sql) in enumerate(conn.calls) if i > i_read and "SET LOCAL ROLE" in sql
    )
    i_load = _index(conn, "INSERT INTO ohlcv_load")
    i_bars = _index(conn, "INSERT INTO market_data_ohlcv", kind="executemany")
    i_flag = _index(conn, "INSERT INTO bar_quality_flag", kind="executemany")
    i_digest = _index(conn, "INSERT INTO bar_content_digest", kind="executemany")
    assert i_read < i_role < i_load < i_bars < i_flag < i_digest

    digests = _many_rows(conn, "INSERT INTO bar_content_digest")
    expected_5m = _expected_month_digests(fixture, rules={5: ("gap_before_next",)})
    assert {r[1] for r in digests} == {"5m", "15m", "1h"}
    digest_5m = next(r for r in digests if r[1] == "5m")
    assert digest_5m[2] == _JUNE and digest_5m[4] == expected_5m[_JUNE]
    assert digest_5m[7] == 78 and digest_5m[8] == _BATCH_ID


def test_second_run_over_unchanged_5m_writes_no_bar_and_no_digest():
    fixture = _five_minute_fixture()
    flags = {"SPY": [(fixture[5][0], "gap_before_next", False)]}
    stored, stored_flags, digests = _stored_from_first_run(fixture, flags=flags)

    conn = FakeConn(
        bars={"SPY": fixture},
        flags=flags,
        stored_grid={"SPY": stored},
        stored_grid_flags={"SPY": stored_flags},
        current_digests={"SPY": digests},
    )
    assert _run(conn)["derived"] == 1
    assert _bar_writes(conn) == []
    assert not _many_rows(conn, "INSERT INTO bar_content_digest")
    assert not _many_rows(conn, "bar_quality_flag")
    assert not _revisions(conn)
    loads = _load_counts(conn)
    for tf, n in (("15m", 26), ("1h", 7)):
        assert loads[tf]["outcome"] == "applied"
        assert (loads[tf]["n_new"], loads[tf]["n_changed"], loads[tf]["n_removed"]) == (0, 0, 0)
        assert loads[tf]["n_unchanged"] == n


def test_one_changed_5m_bar_rewrites_exactly_its_15m_and_1h_bars_and_month():
    may = _five_minute_fixture(open_at=_MAY_OPEN)
    june = _five_minute_fixture()
    stored, stored_flags, digests = _stored_from_first_run(may + june)

    revised = list(june)
    bar = revised[40]  # 16:50 UTC: 15m bucket 16:45, 1h bucket 16:30
    revised[40] = (bar[0], bar[1], bar[2], bar[3], bar[4] + 0.01, bar[5] + 300, bar[6])
    conn = FakeConn(
        bars={"SPY": may + revised},
        stored_grid={"SPY": stored},
        stored_grid_flags={"SPY": stored_flags},
        current_digests={"SPY": digests},
    )
    assert _run(conn)["derived"] == 1

    upserts = _upserted_bars(conn)
    assert {(r[2], r[0]) for r in upserts} == {
        ("15m", bar[0] - timedelta(minutes=5)),
        ("1h", _SESSION_OPEN + timedelta(hours=3)),
    }
    assert not _inserted_bars(conn)
    assert not any("DELETE FROM market_data_ohlcv" in s for s in _bar_writes(conn))
    upsert_sql = next(
        sql for sql, _ in conn.executemany_calls if "ON CONFLICT" in sql and "market_data" in sql
    )
    assert 'ON CONFLICT ("timestamp", symbol, timeframe) DO UPDATE' in upsert_sql

    # One revision per changed row, origin load, carrying the stored (old) values.
    old_by_key = {(r["timeframe"], r["timestamp"]): r for r in stored}
    revisions = _revisions(conn)
    assert len(revisions) == 2
    load_ids = {str(row["timeframe"]): row["load_id"] for row in _load_counts(conn).values()}
    for rev in revisions:
        load_id, symbol, tf, ts, o, h, lo, c, v, source, origin = rev
        old = old_by_key[(tf, ts)]
        assert (symbol, origin, source) == ("SPY", "load", SOURCE_DERIVED_5M)
        assert load_id == load_ids[tf]
        assert (o, h, lo, c, v) == (
            old["open"],
            old["high"],
            old["low"],
            old["close"],
            old["volume"],
        )
    # i_revision precedes the upsert (old value recorded before it is overwritten).
    assert _index(conn, "INSERT INTO ohlcv_revision", kind="executemany") < _index(
        conn, "ON CONFLICT", kind="executemany"
    )

    # Digests only for June: 5m, 15m, 1h; May's months are untouched.
    rewritten = {(r[1], r[2]) for r in _many_rows(conn, "INSERT INTO bar_content_digest")}
    assert rewritten == {("5m", _JUNE), ("15m", _JUNE), ("1h", _JUNE)}

    loads = _load_counts(conn)
    assert (loads["15m"]["n_changed"], loads["15m"]["n_unchanged"]) == (1, 51)
    assert (loads["1h"]["n_changed"], loads["1h"]["n_unchanged"]) == (1, 13)


def test_a_stored_derived_row_no_longer_derived_is_removed_with_its_old_value():
    fixture = _five_minute_fixture()
    stored, stored_flags, digests = _stored_from_first_run(fixture)
    stale_ts = _SESSION_OPEN + timedelta(days=1)  # Tuesday: no 5m bars, nothing derives
    stale = {
        "timeframe": "15m",
        "timestamp": stale_ts,
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 1.5,
        "volume": 10,
        "source": SOURCE_DERIVED_5M,
    }
    conn = FakeConn(
        bars={"SPY": fixture},
        stored_grid={"SPY": [*stored, stale]},
        stored_grid_flags={"SPY": stored_flags},
        current_digests={"SPY": digests},
    )
    assert _run(conn)["derived"] == 1

    deletes = [(sql, a) for sql, a in conn.statements if "/* delete_stale_derived */" in sql]
    assert len(deletes) == 1
    sql, args = deletes[0]
    assert args[0] == "SPY" and args[1] == "15m" and list(args[2]) == [stale_ts]
    assert "source = 'derived_5m'" in sql
    (rev,) = _revisions(conn)
    assert rev[2:4] == ("15m", stale_ts) and rev[4:10] == (1.0, 2.0, 0.5, 1.5, 10, "derived_5m")
    assert rev[10] == "load"
    assert _load_counts(conn)["15m"]["n_removed"] == 1
    assert _index(conn, "INSERT INTO ohlcv_revision", kind="executemany") < _index(
        conn, "/* delete_stale_derived */"
    )


# ---------------------------------------------------------------------------
# Stored vendor rows: archive, archive_segment revisions, verify by value, delete
# ---------------------------------------------------------------------------


def _vendor(tf: str, ts: datetime, close: float) -> dict:
    return {
        "timeframe": tf,
        "timestamp": ts,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 500,
        "source": "ibkr_named",
    }


def test_stored_vendor_rows_are_archived_recorded_verified_then_deleted():
    fixture = _five_minute_fixture()
    vendor = [
        _vendor("15m", _SESSION_OPEN, 99.0),  # the key a derived row replaces
        _vendor("1h", _SESSION_OPEN - timedelta(days=30), 98.0),  # older than any 5m
    ]
    conn = FakeConn(bars={"SPY": fixture}, stored_grid={"SPY": vendor})
    totals = _run(conn)
    assert totals["derived"] == 1 and totals["failed"] == 0

    i_load = _index(conn, "INSERT INTO ohlcv_load")
    i_archive = _index(conn, "INSERT INTO ohlcv_intraday_raw_archive")
    i_segment = _index(conn, "'archive_segment'")
    i_verify = _index(conn, "/* vendor_removal_verify */", kind="fetchrow")
    i_delete = _index(conn, "/* delete_vendor_rows */")
    i_insert = _index(conn, "INSERT INTO market_data_ohlcv", kind="executemany")
    assert i_load < i_archive < i_segment < i_verify < i_delete < i_insert

    # The archive_segment revision is one INSERT ... SELECT per grid timeframe, under that
    # timeframe's load row, keeping a stored vendor row whose archived row is not equal.
    load_ids = {str(row["timeframe"]): row["load_id"] for row in _load_counts(conn).values()}
    segment = [(sql, a) for sql, a in conn.statements if "'archive_segment'" in sql]
    assert sorted((a[1], a[2]) for _, a in segment) == sorted(
        (tf, load_ids[tf]) for tf in ("15m", "1h")
    )
    segment_sql = segment[0][0]
    assert "INSERT INTO ohlcv_revision" in segment_sql
    assert "LEFT JOIN ohlcv_intraday_raw_archive" in segment_sql
    for field in ("open", "high", "low", "close", "volume"):
        assert f"a.{field} <> m.{field}" in segment_sql
    assert "IS DISTINCT FROM 'derived_5m'" in segment_sql

    verify_sql = next(sql for k, sql in conn.calls if "/* vendor_removal_verify */" in sql)
    assert "ohlcv_intraday_raw_archive" in verify_sql and "ohlcv_revision" in verify_sql
    delete_sql, delete_args = next(
        (sql, a) for sql, a in conn.statements if "/* delete_vendor_rows */" in sql
    )
    assert "IS DISTINCT FROM 'derived_5m'" in delete_sql
    assert list(delete_args[1]) == ["15m", "1h"]

    # The derived row at the vendor key is new (the vendor row is not a derived revision).
    assert any(r[2] == "15m" and r[0] == _SESSION_OPEN for r in _inserted_bars(conn))
    assert not _upserted_bars(conn)
    detail = [a for sql, a in conn.statements if "UPDATE bar_derivation_batch" in sql]
    assert detail and json.loads(detail[-1][2])["n_archive_rows"] == 2


def test_an_unmatched_vendor_row_fails_the_symbol_and_writes_nothing():
    fixture = _five_minute_fixture()
    conn = FakeConn(
        bars={"SPY": fixture},
        stored_grid={"SPY": [_vendor("15m", _SESSION_OPEN, 99.0)]},
        verify_row={"n_removable": 1, "n_unmatched": 1},
    )
    with pytest.raises(RuntimeError, match="1 symbol failure"):
        _run(conn)
    assert not any("DELETE FROM market_data_ohlcv" in s for s in _bar_writes(conn))
    assert not _inserted_bars(conn) and not _upserted_bars(conn)
    assert ("<rollback>", "") in conn.calls
    closed = [a for sql, a in conn.statements if "UPDATE bar_derivation_batch" in sql]
    assert closed[-1][0] == _BATCH_ID and "failed" in closed[-1]


def test_a_removable_count_that_disagrees_with_the_read_fails_the_symbol():
    fixture = _five_minute_fixture()
    conn = FakeConn(
        bars={"SPY": fixture},
        stored_grid={"SPY": [_vendor("15m", _SESSION_OPEN, 99.0)]},
        verify_row={"n_removable": 2, "n_unmatched": 0},
    )
    with pytest.raises(RuntimeError, match="1 symbol failure"):
        _run(conn)
    assert not _bar_writes(conn)


# ---------------------------------------------------------------------------
# Revision-ratio refusal
# ---------------------------------------------------------------------------


def test_a_broad_restatement_is_refused_recorded_and_fails_the_batch():
    fixture = _five_minute_fixture()
    stored, stored_flags, digests = _stored_from_first_run(fixture)
    shifted = [dict(r, close=r["close"] + 1.0) for r in stored]  # every derived row differs
    conn = FakeConn(
        bars={"SPY": fixture},
        stored_grid={"SPY": shifted},
        stored_grid_flags={"SPY": stored_flags},
        current_digests={"SPY": digests},
        apr={
            "threshold.bar_integrity.max_revision_ratio": "0.02",
            "threshold.bar_integrity.revision_ratio_min_stored": "5",
        },
    )
    with pytest.raises(RuntimeError, match="refused"):
        _run(conn)
    assert _bar_writes(conn) == []
    assert not _revisions(conn)
    assert not _many_rows(conn, "INSERT INTO bar_content_digest")
    loads = _load_counts(conn)
    assert {row["outcome"] for row in loads.values()} == {"refused"}
    assert loads["15m"]["n_changed"] == 26
    # The refusal is a recorded finding: its load rows commit.
    i_load = _index(conn, "INSERT INTO ohlcv_load")
    assert ("<commit>", "") in conn.calls[i_load:]
    closed = [a for sql, a in conn.statements if "UPDATE bar_derivation_batch" in sql]
    assert "failed" in closed[-1]


def test_a_restatement_below_min_stored_is_written_not_refused():
    fixture = _five_minute_fixture()
    stored, stored_flags, digests = _stored_from_first_run(fixture)
    shifted = [dict(r, close=r["close"] + 1.0) for r in stored]
    conn = FakeConn(
        bars={"SPY": fixture},
        stored_grid={"SPY": shifted},
        stored_grid_flags={"SPY": stored_flags},
        current_digests={"SPY": digests},
    )  # seeded min_stored 500 > 33 stored rows
    assert _run(conn)["derived"] == 1
    assert len(_upserted_bars(conn)) == 33


# ---------------------------------------------------------------------------
# Skips, dry run, exclusions, flags
# ---------------------------------------------------------------------------


def test_symbol_without_5m_is_skipped_without_statements():
    conn = FakeConn(bars={"SPY": _five_minute_fixture(), "NOFIVE": []})
    totals = _run(conn, symbols=["SPY", "NOFIVE"])
    assert totals["no_5m"] == 1 and totals["derived"] == 1
    assert not any("NOFIVE" in str(a) for _, a in conn.statements)
    assert not any(
        any("NOFIVE" in str(x) for x in row) for _, rows in conn.executemany_calls for row in rows
    )


def test_changed_only_skips_symbol_whose_5m_digests_are_current():
    expected = _expected_month_digests(_five_minute_fixture())
    current = {"SPY": [("5m", start, digest) for start, digest in expected.items()]}
    conn = FakeConn(bars={"SPY": _five_minute_fixture()}, current_digests=current)
    totals = _run(conn, changed_only=True)
    assert totals["unchanged"] == 1 and totals["derived"] == 0
    assert not _bar_writes(conn) and not _loads(conn)


def test_changed_only_processes_symbol_when_digest_differs():
    expected = _expected_month_digests(_five_minute_fixture())
    stale = {"SPY": [("5m", start, "0" * 64) for start in expected]}
    conn = FakeConn(bars={"SPY": _five_minute_fixture()}, current_digests=stale)
    assert _run(conn, changed_only=True)["derived"] == 1
    assert _inserted_bars(conn)


def test_changed_only_selects_symbol_with_new_answered_window():
    expected = _expected_month_digests(_five_minute_fixture())
    current = {"SPY": [("5m", start, digest) for start, digest in expected.items()]}
    conn = FakeConn(bars={"SPY": _five_minute_fixture()}, current_digests=current)
    assert _run(conn, changed_only=True)["unchanged"] == 1
    conn = FakeConn(
        bars={"SPY": _five_minute_fixture()}, current_digests=current, answered_since=True
    )
    totals = _run(conn, changed_only=True)
    assert totals["derived"] == 1 and totals["unchanged"] == 0


def test_dry_run_reads_and_classifies_but_writes_nothing():
    fixture = _five_minute_fixture()
    conn = FakeConn(bars={"SPY": fixture}, stored_grid={"SPY": [_vendor("15m", _SESSION_OPEN, 1)]})
    totals = _run(conn, apply=False)
    assert totals["derived"] == 1 and totals["derived_rows"] == 33
    assert totals["rows_new"] == 33 and totals["vendor_rows_removed"] == 1
    assert not conn.statements, conn.statements
    assert not conn.executemany_calls
    assert not any(k == "fetchval" for k, _ in conn.calls)


def test_constituent_flags_list_kept_bar_rules_and_quarantine_excludes():
    fixture = _five_minute_fixture()
    flags = {
        "SPY": [
            (fixture[1][0], "gap_before_next", False),
            (fixture[40][0], "price_sanity", True),
        ]
    }
    conn = FakeConn(bars={"SPY": fixture}, flags=flags)
    assert _run(conn)["derived"] == 1

    rows_15m = sorted((r for r in _inserted_bars(conn) if r[2] == "15m"), key=lambda r: r[0])
    bucket_13 = rows_15m[13]
    assert bucket_13[4] == pytest.approx(fixture[41][2])
    assert bucket_13[7] == fixture[39][5] + fixture[41][5]

    flag_rows = _many_rows(conn, "INSERT INTO bar_quality_flag")
    assert len(flag_rows) == 2
    by_tf = {r[1]: r for r in flag_rows}
    for row in by_tf.values():
        assert row[0] == "SPY" and row[3] == "constituent_flag" and row[4] == GRID_RULE_VERSION
        assert row[6] is False and row[8] == _BATCH_ID
        assert json.loads(row[7])["constituent_rules"] == ["gap_before_next"]
    assert by_tf["15m"][2] == _SESSION_OPEN and by_tf["1h"][2] == _SESSION_OPEN

    expected = _expected_month_digests(
        fixture, drop=frozenset({40}), rules={1: ("gap_before_next",)}
    )
    digest_5m = next(r for r in _many_rows(conn, "INSERT INTO bar_content_digest") if r[1] == "5m")
    assert digest_5m[7] == 77 and digest_5m[4] == expected[_JUNE]


def _partial_flags(conn: FakeConn) -> list[tuple]:
    return [
        r
        for r in _many_rows(conn, "INSERT INTO bar_quality_flag")
        if r[3] == "partial_constituents"
    ]


def _answered_windows_for_slot(slot: datetime):
    return {"SPY": [(slot - timedelta(minutes=5), slot + timedelta(minutes=10))]}


def test_complete_bar_without_holes_gets_no_partial_flag():
    conn = FakeConn(bars={"SPY": _five_minute_fixture()})
    assert _run(conn)["derived"] == 1
    assert _partial_flags(conn) == []


def test_hole_without_answered_window_is_flagged_partial():
    fixture = _five_minute_fixture()
    holed = fixture[:40] + fixture[41:]
    conn = FakeConn(bars={"SPY": holed})
    assert _run(conn)["derived"] == 1
    by_key = {(r[1], r[2]): r for r in _partial_flags(conn)}
    slot_40 = fixture[40][0]
    assert set(by_key) == {
        ("15m", slot_40 - timedelta(minutes=5)),
        ("1h", _SESSION_OPEN + timedelta(hours=3)),
    }
    for row in by_key.values():
        assert row[4] == GRID_RULE_VERSION and row[6] is False and row[8] == _BATCH_ID
        assert json.loads(row[7])["missing_slots"] == 1


def test_answered_window_covers_the_hole_and_no_flag_is_written():
    fixture = _five_minute_fixture()
    holed = fixture[:40] + fixture[41:]
    conn = FakeConn(
        bars={"SPY": holed}, answered_windows=_answered_windows_for_slot(fixture[40][0])
    )
    assert _run(conn)["derived"] == 1
    assert _partial_flags(conn) == []


def test_partial_flag_does_not_change_the_digest():
    fixture = _five_minute_fixture()
    holed = fixture[:40] + fixture[41:]

    def _digests(answered: bool) -> dict[str, str]:
        conn = FakeConn(
            bars={"SPY": holed},
            answered_windows=_answered_windows_for_slot(fixture[40][0]) if answered else {},
        )
        assert _run(conn)["derived"] == 1
        return {r[1]: r[4] for r in _many_rows(conn, "INSERT INTO bar_content_digest")}

    assert _digests(answered=False) == _digests(answered=True)


def test_a_later_answered_window_clears_the_stale_partial_flag_without_a_bar_write():
    """todo 462: the flag is replaced by key, so an answer that arrives later deletes it even
    though no bar changed (the --changed-only answered_since path)."""
    fixture = _five_minute_fixture()
    holed = fixture[:40] + fixture[41:]
    stored, stored_flags, digests = _stored_from_first_run(holed)
    assert {f["rule"] for f in stored_flags} == {"partial_constituents"}

    conn = FakeConn(
        bars={"SPY": holed},
        stored_grid={"SPY": stored},
        stored_grid_flags={"SPY": stored_flags},
        current_digests={"SPY": digests},
        answered_windows=_answered_windows_for_slot(fixture[40][0]),
    )
    assert _run(conn)["derived"] == 1
    assert _bar_writes(conn) == []
    deleted = _many_rows(conn, "DELETE FROM bar_quality_flag")
    assert sorted((r[1], r[3]) for r in deleted) == [
        ("15m", "partial_constituents"),
        ("1h", "partial_constituents"),
    ]
    assert _partial_flags(conn) == []


# ---------------------------------------------------------------------------
# Shared planner and statement shapes
# ---------------------------------------------------------------------------


def test_coverage_rule_comes_from_the_shared_planner():
    from services import bar_derivation

    assert bar_derivation.AnsweredWindows is gap_plan.AnsweredWindows
    assert set(bar_derivation.ANSWERED_OUTCOMES) == {"bars", "no_data"}


def test_answered_windows_sql_parameterizes_the_route():
    from services import bar_derivation

    sql = bar_derivation._SELECT_ANSWERED_WINDOWS_SQL
    assert "r.route = $3" in sql
    assert "r.what_to_show = $4" in sql


def test_the_grid_uses_the_write_contract_and_no_segment_rewrite():
    from services import bar_derivation
    from src.intelligence.bars import write_contract

    assert bar_derivation.classify is write_contract.classify
    assert not hasattr(bar_derivation, "_DELETE_SEGMENT_SQL")
    assert not hasattr(bar_derivation, "_ARCHIVE_VERIFY_SQL")
    assert "UPDATE market_data_ohlcv" not in Path(bar_derivation.__file__).read_text()
