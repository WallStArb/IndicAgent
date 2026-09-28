"""Tests for services/bar_derivation.py --stage grid (phase 185 plan 11, task 2).

Fakes only, no DB: a fake pool answering the read shapes the grid stage issues
(config_state APR rows, DISTINCT-symbol discovery over tradeable 5m, per-symbol
5m bars from market_data_ohlcv_tradeable, bar_quality_flag rules,
bar_content_digest_current) and a fake connection recording every call in
chronological order. The contract under test (D-15): one transaction per symbol
in the order SET LOCAL ROLE, archive INSERT ... SELECT, count/value checksum
compare, segment DELETE, derived write, constituent_flag flags, digest rows for
5m/15m/1h months; a checksum mismatch rolls the symbol back; no-5m, unchanged
(--changed-only) and excluded-lane symbols are skipped without statements;
dry-run computes and writes nothing.

Derived values are checked against direct arithmetic over the same 5m fixture
(plan 06's direct-oracle convention), never against the implementation's own
aggregation path.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from structlog.testing import capture_logs

from services.bar_derivation import BarDerivation
from src.intelligence.bars.digest import DIGEST_ALGORITHM, bar_content_digest, month_ranges
from src.intelligence.bars.sources import GRID_RULE_VERSION, SOURCE_DERIVED_5M

_BATCH_ID = "11111111-1111-1111-1111-111111111111"
# Monday 2024-06-03, regular NYSE session 13:30-20:00 UTC.
_SESSION_OPEN = datetime(2024, 6, 3, 13, 30, tzinfo=UTC)
_SESSION_CLOSE = datetime(2024, 6, 3, 20, 0, tzinfo=UTC)


def _five_minute_fixture(n: int = 78) -> list[tuple]:
    """n 5m bars on one full session: wandering prices, distinct volumes."""
    rows: list[tuple] = []
    for i in range(n):
        px = 100.0 + 0.05 * i
        rows.append(
            (
                _SESSION_OPEN + timedelta(seconds=300 * i),
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
    """(ts_seconds, ohlcv arrays, base) over the kept rows, direct from the fixture."""
    kept = [r for i, r in enumerate(rows) if i not in drop]
    return (
        np.array([int(r[0].timestamp()) for r in kept], dtype=np.int64),
        np.array([r[1] for r in kept], dtype=np.float64),
        np.array([r[2] for r in kept], dtype=np.float64),
        np.array([r[3] for r in kept], dtype=np.float64),
        np.array([r[4] for r in kept], dtype=np.float64),
        np.array([r[5] for r in kept], dtype=np.float64),
        kept[0][6],
    )


def _expected_month_digests(rows: list[tuple], drop: frozenset[int] = frozenset()):
    """(range_start -> digest, range_start -> n_rows) computed directly from the fixture."""
    ts, o, h, lo, c, v, _ = _fixture_arrays(rows, drop)
    out: dict[datetime, tuple[str, int]] = {}
    for start, end in month_ranges(ts):
        mask = (ts >= int(start.timestamp())) & (ts < int(end.timestamp()))
        digest = bar_content_digest(
            ts[mask],
            o[mask],
            h[mask],
            lo[mask],
            c[mask],
            v[mask],
            [() for _ in range(int(mask.sum()))],
        )
        out[start] = (digest, int(mask.sum()))
    return out


class FakeConn:
    """asyncpg.Connection-shaped fake recording every call chronologically."""

    def __init__(
        self,
        *,
        bars: dict[str, list[tuple]],
        flags: dict[str, list[tuple]] | None = None,
        current_digests: dict[str, list[tuple]] | None = None,
        verify_row: dict[str, object] | None = None,
    ) -> None:
        self.bars = bars
        self.flags = flags or {}
        self.current_digests = current_digests or {}
        self.verify_row = verify_row
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

    async def fetch(self, sql: str, *args: object) -> list[object]:
        self.calls.append(("fetch", sql))
        if "config_state" in sql:
            return [{"config_key": "infra.bar_derivation.grid_symbol_batch", "config_value": "10"}]
        if "DISTINCT symbol" in sql:
            return [(symbol,) for symbol in sorted(self.bars)]
        if "market_data_ohlcv_tradeable" in sql:
            return list(self.bars[str(args[0])])
        if "bar_quality_flag" in sql:
            return list(self.flags.get(str(args[0]), []))
        if "bar_content_digest_current" in sql:
            return list(self.current_digests.get(str(args[0]), []))
        raise AssertionError(f"unexpected fetch: {sql}")

    async def fetchrow(self, sql: str, *args: object) -> object:
        self.calls.append(("fetchrow", sql))
        assert "ohlcv_intraday_raw_archive" in sql, f"unexpected fetchrow: {sql}"
        if self.verify_row is not None:
            return self.verify_row
        return {
            "n_removable": 5,
            "n_archived": 5,
            "removable_value_sum": 30.0,
            "archived_value_sum": 30.0,
            "removable_volume_sum": 5000,
            "archived_volume_sum": 5000,
        }

    async def fetchval(self, sql: str, *args: object) -> object:
        self.calls.append(("fetchval", sql))
        assert "bar_derivation_batch" in sql, f"unexpected fetchval: {sql}"
        return _BATCH_ID

    async def execute(self, sql: str, *args: object) -> str:
        self.calls.append(("execute", sql))
        self.statements.append((sql, tuple(args)))
        if sql.startswith("DELETE FROM market_data_ohlcv"):
            return "DELETE 7"
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


def _run(conn: FakeConn, **overrides: object) -> None:
    writer = BarDerivation(
        "postgresql://unused",
        stage="grid",
        symbols=overrides.pop("symbols", None),
        changed_only=overrides.pop("changed_only", False),
        apply=overrides.pop("apply", True),
        exclude_symbols_file=overrides.pop("exclude_symbols_file", None),
    )
    asyncio.run(writer.execute(FakePool(conn)))


def _derived_rows(conn: FakeConn, table: str) -> list[tuple]:
    rows: list[tuple] = []
    for sql, args in conn.executemany_calls:
        if f"INSERT INTO {table}" in sql:
            rows.extend(args)
    return rows


def _first_index(conn: FakeConn, marker: str, kind: str = "execute") -> int:
    for i, (k, sql) in enumerate(conn.calls):
        if k == kind and marker in sql:
            return i
    raise AssertionError(f"no {kind} call containing {marker!r}")


def _done_totals(records: list[dict]) -> dict[str, int]:
    events = [r for r in records if r["event"] == "bar_derivation.done"]
    assert events, "no bar_derivation.done event"
    return events[0]


def test_full_session_derives_grid_in_transaction_order():
    conn = FakeConn(bars={"SPY": _five_minute_fixture()})
    with capture_logs() as records:
        _run(conn)
    totals = _done_totals(records)
    assert totals["derived"] == 1 and totals["failed"] == 0

    rows_15m = [r for r in _derived_rows(conn, "market_data_ohlcv") if r[2] == "15m"]
    rows_1h = [r for r in _derived_rows(conn, "market_data_ohlcv") if r[2] == "1h"]
    assert len(rows_15m) == 26
    assert len(rows_1h) == 7
    assert all(r[8] == SOURCE_DERIVED_5M for r in rows_15m + rows_1h)

    # Direct-oracle spot values: first 15m bar from fixture bars 0-2, last 1h bar
    # (15:30-16:00 ET, six constituents) from fixture bars 72-77.
    first = rows_15m[0]
    assert first[0] == _SESSION_OPEN
    assert first[1] == 100.0
    assert first[2] == pytest.approx(100.0 + 0.05 * 2 + 0.02)
    assert first[3] == pytest.approx(100.0 - 0.02)
    assert first[4] == pytest.approx(100.0 + 0.05 * 2 + 0.01)
    assert first[5] == 1000 + 1001 + 1002
    last_1h = rows_1h[-1]
    assert last_1h[0] == _SESSION_OPEN + timedelta(hours=6)
    assert last_1h[5] == sum(1000 + i for i in range(72, 78))
    # D-15 identity: per-day derived 1h volume sums equal the 5m volume sum.
    assert sum(r[5] for r in rows_1h) == sum(r[5] for r in _five_minute_fixture())

    # Transaction order: role, archive INSERT ... SELECT, checksum fetchrow,
    # segment DELETE, derived write, flags, digest rows.
    i_role = _first_index(conn, "SET LOCAL ROLE")
    i_archive = _first_index(conn, "INSERT INTO ohlcv_intraday_raw_archive")
    i_verify = _first_index(conn, "ohlcv_intraday_raw_archive", kind="fetchrow")
    i_delete = _first_index(conn, "DELETE FROM market_data_ohlcv")
    i_derived = _first_index(conn, "INSERT INTO market_data_ohlcv", kind="executemany")
    i_flag = _first_index(conn, "INSERT INTO bar_quality_flag", kind="executemany")
    i_digest = _first_index(conn, "INSERT INTO bar_content_digest", kind="executemany")
    assert i_role < i_archive < i_verify < i_delete < i_derived < i_flag < i_digest
    # The archive insert excludes synthetic placeholders.
    archive_sql = next(
        sql
        for sql, _ in conn.statements
        if sql.startswith("INSERT INTO ohlcv_intraday_raw_archive")
    )
    assert "source <> 'synthetic_fill'" in archive_sql
    delete_args = next(
        a for sql, a in conn.statements if sql.startswith("DELETE FROM market_data_ohlcv")
    )
    assert delete_args[1] == ("15m", "1h")

    # Digest rows: one per (tf, month) for 5m, 15m and 1h, rule version beside.
    digest_rows = _derived_rows(conn, "bar_content_digest")
    by_tf = {tf: [r for r in digest_rows if r[1] == tf] for tf in ("5m", "15m", "1h")}
    expected_5m = _expected_month_digests(_five_minute_fixture())
    for tf, n_expected in (("5m", 78), ("15m", 26), ("1h", 7)):
        assert len(by_tf[tf]) == 1
        row = by_tf[tf][0]
        assert row[0] == "SPY" and row[5] == DIGEST_ALGORITHM and row[6] == GRID_RULE_VERSION
        assert row[7] == n_expected
        assert row[8] == _BATCH_ID
    assert by_tf["5m"][0][4] == expected_5m[datetime(2024, 6, 1, tzinfo=UTC)][0]
    assert by_tf["5m"][0][2] == datetime(2024, 6, 1, tzinfo=UTC)

    # Batch provenance opened and closed (stage grid, rule version recorded).
    opened = [sql for k, sql in conn.calls if k == "fetchval" and "bar_derivation_batch" in sql]
    assert opened and "INSERT INTO bar_derivation_batch" in opened[0]
    closed = [sql for sql, _ in conn.statements if sql.startswith("UPDATE bar_derivation_batch")]
    assert closed


def test_checksum_mismatch_rolls_back_symbol():
    conn = FakeConn(
        bars={"SPY": _five_minute_fixture()},
        verify_row={
            "n_removable": 7,
            "n_archived": 6,
            "removable_value_sum": 30.0,
            "archived_value_sum": 30.0,
            "removable_volume_sum": 5000,
            "archived_volume_sum": 5000,
        },
    )
    with capture_logs() as records, pytest.raises(RuntimeError, match="1 symbol failure"):
        _run(conn)
    totals = _done_totals(records)
    assert totals["failed"] == 1
    # The segment DELETE never ran: nothing leaves market_data_ohlcv unverified.
    assert not any(sql.startswith("DELETE FROM market_data_ohlcv") for sql, _ in conn.statements)
    assert not _derived_rows(conn, "market_data_ohlcv")


def test_symbol_without_5m_is_skipped_without_statements():
    conn = FakeConn(bars={"SPY": _five_minute_fixture(), "NOFIVE": []})
    with capture_logs() as records:
        _run(conn, symbols=["SPY", "NOFIVE"])
    totals = _done_totals(records)
    assert totals["no_5m"] == 1 and totals["derived"] == 1
    assert not any("NOFIVE" in str(a) for _, a in conn.statements)
    assert not any(
        any("NOFIVE" in str(x) for x in row) for _, rows in conn.executemany_calls for row in rows
    )


def test_changed_only_skips_symbol_whose_5m_digests_are_current():
    expected = _expected_month_digests(_five_minute_fixture())
    current = {
        symbol: [(start, digest) for start, (digest, _n) in expected.items()] for symbol in ("SPY",)
    }
    conn = FakeConn(bars={"SPY": _five_minute_fixture()}, current_digests=current)
    with capture_logs() as records:
        _run(conn, changed_only=True)
    totals = _done_totals(records)
    assert totals["unchanged"] == 1 and totals["derived"] == 0
    assert not any(
        sql.startswith(("INSERT INTO ohlcv", "DELETE FROM market_data"))
        for sql, _ in conn.statements
    )


def test_changed_only_processes_symbol_when_digest_differs():
    expected = _expected_month_digests(_five_minute_fixture())
    stale = [(start, "0" * 64) for start, _ in expected.items()]
    conn = FakeConn(bars={"SPY": _five_minute_fixture()}, current_digests={"SPY": stale})
    with capture_logs() as records:
        _run(conn, changed_only=True)
    assert _done_totals(records)["derived"] == 1
    assert _derived_rows(conn, "market_data_ohlcv")


def test_dry_run_issues_no_write_statements():
    conn = FakeConn(bars={"SPY": _five_minute_fixture()})
    with capture_logs() as records:
        _run(conn, apply=False)
    totals = _done_totals(records)
    assert totals["derived"] == 1 and totals["derived_rows"] == 33
    assert not conn.statements, conn.statements
    assert not conn.executemany_calls
    # No batch row either: dry-run attributes nothing.
    assert not any(k == "fetchval" for k, _ in conn.calls)


def test_excluded_lane_symbol_is_skipped(tmp_path):
    lane_file = tmp_path / "lanes.txt"
    lane_file.write_text("# lane guard\nSPY\n")
    conn = FakeConn(bars={"SPY": _five_minute_fixture(), "QQQ": _five_minute_fixture()})
    with capture_logs() as records:
        _run(conn, exclude_symbols_file=str(lane_file))
    totals = _done_totals(records)
    assert totals["excluded_lane"] == 1 and totals["derived"] == 1
    written = {r[0] for r in _derived_rows(conn, "market_data_ohlcv")}
    assert written == {"QQQ"}


def test_constituent_flags_list_kept_bar_rules_and_quarantine_excludes():
    fixture = _five_minute_fixture()
    flags = {
        "SPY": [
            (fixture[1][0], "gap_before_next", False),
            (fixture[40][0], "price_sanity", True),
        ]
    }
    conn = FakeConn(bars={"SPY": fixture}, flags=flags)
    with capture_logs() as records:
        _run(conn)
    assert _done_totals(records)["derived"] == 1

    # Quarantined bar 40 is excluded from aggregation: bucket 13 (bars 39-41)
    # aggregates only bars 39 and 41, so its high misses bar 40's value.
    rows_15m = sorted(
        (r for r in _derived_rows(conn, "market_data_ohlcv") if r[2] == "15m"), key=lambda r: r[0]
    )
    bucket_13 = rows_15m[13]
    assert bucket_13[2] == pytest.approx(fixture[41][2])  # high = bar 41's high, bar 40's skipped
    assert bucket_13[5] == fixture[39][5] + fixture[41][5]

    # Constituent flags: one 15m row (bucket 0 contains flagged bar 1) and one
    # 1h row (bucket 0 spans bars 0-11); the quarantined bar contributes nothing.
    flag_rows = _derived_rows(conn, "bar_quality_flag")
    assert len(flag_rows) == 2
    by_tf = {r[1]: r for r in flag_rows}
    for tf, row in by_tf.items():
        assert row[0] == "SPY" and row[3] == "constituent_flag" and row[4] == GRID_RULE_VERSION
        assert row[6] is False and row[8] == _BATCH_ID
        assert json.loads(row[7])["constituent_rules"] == ["gap_before_next"]
    assert by_tf["15m"][2] == _SESSION_OPEN
    assert by_tf["1h"][2] == _SESSION_OPEN

    # 5m digest covers the 77 kept bars with bar 1's rule serialized in.
    expected = _expected_month_digests(
        fixture,
        drop=frozenset({40}),
    )
    digest_5m = next(r for r in _derived_rows(conn, "bar_content_digest") if r[1] == "5m")
    assert digest_5m[7] == 77
