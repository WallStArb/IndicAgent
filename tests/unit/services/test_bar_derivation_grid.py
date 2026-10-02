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

from services.bar_derivation import BarDerivation
from src.intelligence.bars import gap_plan
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


def _expected_month_digests(
    rows: list[tuple],
    drop: frozenset[int] = frozenset(),
    rules: dict[int, tuple[str, ...]] | None = None,
):
    """(range_start -> digest, range_start -> n_rows) computed directly from the fixture.

    ``rules`` maps fixture index -> that bar's informational flag rules, mirroring
    the digest input contract: values plus flag state of the kept bars.
    """
    rules = rules or {}
    ts, o, h, lo, c, v, _ = _fixture_arrays(rows, drop)
    kept_rules = [rules.get(i, ()) for i in range(len(rows)) if i not in drop]
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
            [kept_rules[i] for i in np.flatnonzero(mask)],
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
        answered_windows: dict[str, list[tuple[datetime, datetime]]] | None = None,
        answered_since: bool = False,
    ) -> None:
        self.bars = bars
        self.flags = flags or {}
        self.current_digests = current_digests or {}
        self.verify_row = verify_row
        self.answered_windows = answered_windows or {}
        self.answered_since = answered_since
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
            # asyncpg Records are mapping-shaped; the implementation reads by name.
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
                for r in self.bars[str(args[0])]
            ]
        if "bar_quality_flag" in sql:
            return [
                {"timestamp": t, "rule": rule, "quarantine": q}
                for t, rule, q in self.flags.get(str(args[0]), [])
            ]
        if "bar_content_digest_current" in sql:
            return [
                {"range_start": start, "digest": digest}
                for start, digest in self.current_digests.get(str(args[0]), [])
            ]
        if "ohlcv_request" in sql:
            # The answered 5m SMART TRADES windows (task 1b's coverage read).
            return [
                {"window_start": start, "window_end": end}
                for start, end in self.answered_windows.get(str(args[0]), [])
            ]
        raise AssertionError(f"unexpected fetch: {sql}")

    async def fetchrow(self, sql: str, *args: object) -> object:
        self.calls.append(("fetchrow", sql))
        if "answered_since" in sql:
            return {"answered_since": self.answered_since}
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
        if sql.lstrip().startswith("DELETE FROM market_data_ohlcv"):
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


def _run(conn: FakeConn, **overrides: object) -> dict[str, int]:
    """Run the grid stage against the fake pool; returns the outcome totals."""
    writer = BarDerivation(
        "postgresql://unused",
        stage="grid",
        symbols=overrides.pop("symbols", None),
        changed_only=overrides.pop("changed_only", False),
        apply=overrides.pop("apply", True),
        exclude_symbols_file=overrides.pop("exclude_symbols_file", None),
    )
    return asyncio.run(writer.execute(FakePool(conn)))


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


def test_full_session_derives_grid_in_transaction_order():
    fixture = _five_minute_fixture()
    conn = FakeConn(
        bars={"SPY": fixture}, flags={"SPY": [(fixture[5][0], "gap_before_next", False)]}
    )
    totals = _run(conn)
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
    assert first[3] == 100.0
    assert first[4] == pytest.approx(100.0 + 0.05 * 2 + 0.02)
    assert first[5] == pytest.approx(100.0 - 0.02)
    assert first[6] == pytest.approx(100.0 + 0.05 * 2 + 0.01)
    assert first[7] == 1000 + 1001 + 1002
    last_1h = rows_1h[-1]
    assert last_1h[0] == _SESSION_OPEN + timedelta(hours=6)
    assert last_1h[7] == sum(1000 + i for i in range(72, 78))
    # D-15 identity: per-day derived 1h volume sums equal the 5m volume sum.
    assert sum(r[7] for r in rows_1h) == sum(r[5] for r in _five_minute_fixture())

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
        if sql.lstrip().startswith("INSERT INTO ohlcv_intraday_raw_archive")
    )
    assert "source <> 'synthetic_fill'" in archive_sql
    delete_args = next(
        a for sql, a in conn.statements if sql.lstrip().startswith("DELETE FROM market_data_ohlcv")
    )
    assert list(delete_args[1]) == ["15m", "1h"]

    # Digest rows: one per (tf, month) for 5m, 15m and 1h, rule version beside.
    digest_rows = _derived_rows(conn, "bar_content_digest")
    by_tf = {tf: [r for r in digest_rows if r[1] == tf] for tf in ("5m", "15m", "1h")}
    expected_5m = _expected_month_digests(_five_minute_fixture(), rules={5: ("gap_before_next",)})
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
    closed = [
        sql for sql, _ in conn.statements if sql.lstrip().startswith("UPDATE bar_derivation_batch")
    ]
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
    with pytest.raises(RuntimeError, match="1 symbol failure"):
        _run(conn)
    # The segment DELETE never ran: nothing leaves market_data_ohlcv unverified.
    assert not any(
        sql.lstrip().startswith("DELETE FROM market_data_ohlcv") for sql, _ in conn.statements
    )
    assert not _derived_rows(conn, "market_data_ohlcv")


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
    current = {
        symbol: [(start, digest) for start, (digest, _n) in expected.items()] for symbol in ("SPY",)
    }
    conn = FakeConn(bars={"SPY": _five_minute_fixture()}, current_digests=current)
    totals = _run(conn, changed_only=True)
    assert totals["unchanged"] == 1 and totals["derived"] == 0
    assert not any(
        sql.lstrip().startswith(("INSERT INTO ohlcv", "DELETE FROM market_data"))
        for sql, _ in conn.statements
    )


def test_changed_only_processes_symbol_when_digest_differs():
    expected = _expected_month_digests(_five_minute_fixture())
    stale = [(start, "0" * 64) for start, _ in expected.items()]
    conn = FakeConn(bars={"SPY": _five_minute_fixture()}, current_digests={"SPY": stale})
    assert _run(conn, changed_only=True)["derived"] == 1
    assert _derived_rows(conn, "market_data_ohlcv")


def test_dry_run_issues_no_write_statements():
    conn = FakeConn(bars={"SPY": _five_minute_fixture()})
    totals = _run(conn, apply=False)
    assert totals["derived"] == 1 and totals["derived_rows"] == 33
    assert not conn.statements, conn.statements
    assert not conn.executemany_calls
    # No batch row either: dry-run attributes nothing.
    assert not any(k == "fetchval" for k, _ in conn.calls)


def test_excluded_lane_symbol_is_skipped(tmp_path):
    lane_file = tmp_path / "lanes.txt"
    lane_file.write_text("# lane guard\nSPY\n")
    conn = FakeConn(bars={"SPY": _five_minute_fixture(), "QQQ": _five_minute_fixture()})
    totals = _run(conn, exclude_symbols_file=str(lane_file))
    assert totals["excluded_lane"] == 1 and totals["derived"] == 1
    written = {r[1] for r in _derived_rows(conn, "market_data_ohlcv")}
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
    assert _run(conn)["derived"] == 1

    # Quarantined bar 40 is excluded from aggregation: bucket 13 (bars 39-41)
    # aggregates only bars 39 and 41, so its high misses bar 40's value.
    rows_15m = sorted(
        (r for r in _derived_rows(conn, "market_data_ohlcv") if r[2] == "15m"), key=lambda r: r[0]
    )
    bucket_13 = rows_15m[13]
    assert bucket_13[4] == pytest.approx(fixture[41][2])  # high = bar 41's high, bar 40's skipped
    assert bucket_13[7] == fixture[39][5] + fixture[41][5]

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
        rules={1: ("gap_before_next",)},
    )
    digest_5m = next(r for r in _derived_rows(conn, "bar_content_digest") if r[1] == "5m")
    assert digest_5m[7] == 77
    assert digest_5m[4] == expected[datetime(2024, 6, 1, tzinfo=UTC)][0]


# ---------------------------------------------------------------------------
# Task 1b: partial_constituents flags and the --changed-only answered-window
# condition (todo 462: holes stop at the derivation edge).
# ---------------------------------------------------------------------------


def _flags_of(conn: FakeConn, rule: str) -> list[tuple]:
    return [r for r in _derived_rows(conn, "bar_quality_flag") if r[3] == rule]


def _answered_windows_for_slot(slot: datetime):
    """A window generously covering `slot`'s [slot, slot+5m) interval."""
    return {"SPY": [(slot - timedelta(minutes=5), slot + timedelta(minutes=10))]}


def test_complete_bar_without_holes_gets_no_partial_flag():
    fixture = _five_minute_fixture()
    conn = FakeConn(bars={"SPY": fixture})
    totals = _run(conn)
    assert totals["derived"] == 1
    assert _flags_of(conn, "partial_constituents") == []


def test_hole_without_answered_window_is_flagged_partial():
    """Bar 40's slot (16:50 UTC) is absent from the tradeable 5m rows and no
    answered ohlcv_request window covers it: every derived bar over that slot
    (the 15m bucket and the 1h bucket) carries partial_constituents."""
    fixture = _five_minute_fixture()
    holed = fixture[:40] + fixture[41:]
    conn = FakeConn(bars={"SPY": holed})
    totals = _run(conn)
    assert totals["derived"] == 1

    flag_rows = _flags_of(conn, "partial_constituents")
    by_key = {(r[1], r[2]): r for r in flag_rows}
    slot_40 = fixture[40][0]
    hour_bucket = _SESSION_OPEN + timedelta(hours=3)  # the 16:30-17:30 bucket
    assert set(by_key) == {
        ("15m", slot_40 - timedelta(minutes=5)),  # the 16:45 15m bucket
        ("1h", hour_bucket),
    }
    for row in flag_rows:
        assert row[4] == GRID_RULE_VERSION and row[6] is False and row[8] == _BATCH_ID
        detail = json.loads(row[7])
        assert detail["missing_slots"] == 1


def test_answered_window_covers_the_hole_and_no_flag_is_written():
    """The same hole inside an answered SMART TRADES window (asked, nothing
    traded) is a real observation: no partial flag anywhere."""
    fixture = _five_minute_fixture()
    holed = fixture[:40] + fixture[41:]
    conn = FakeConn(
        bars={"SPY": holed},
        answered_windows=_answered_windows_for_slot(fixture[40][0]),
    )
    assert _run(conn)["derived"] == 1
    assert _flags_of(conn, "partial_constituents") == []


def test_partial_flag_does_not_change_the_digest():
    """The flag is derived-bar metadata, never a digest input: the digest of a
    month with the flag equals the digest of the same month without it."""
    fixture = _five_minute_fixture()
    holed = fixture[:40] + fixture[41:]

    def _digests(answered: bool) -> dict[str, list[tuple]]:
        conn = FakeConn(
            bars={"SPY": holed},
            answered_windows=_answered_windows_for_slot(fixture[40][0]) if answered else {},
        )
        assert _run(conn)["derived"] == 1
        return {r[1]: r[4] for r in _derived_rows(conn, "bar_content_digest")}

    assert _digests(answered=False) == _digests(answered=True)


def test_rewrite_replaces_the_segments_partial_flags():
    """A later answered window must clear a stale flag: the re-derive deletes
    the segment's partial_constituents flags before writing the fresh set
    (here: the hole is unanswered, so a fresh partial flag is written)."""
    fixture = _five_minute_fixture()
    holed = fixture[:40] + fixture[41:]
    conn = FakeConn(bars={"SPY": holed})
    assert _run(conn)["derived"] == 1
    deletes = [
        (sql, args)
        for sql, args in conn.statements
        if sql.lstrip().startswith("DELETE FROM bar_quality_flag")
    ]
    assert len(deletes) == 1
    sql, args = deletes[0]
    assert "partial_constituents" in sql
    assert list(args[1]) == ["15m", "1h"]
    i_delete = _first_index(conn, "DELETE FROM bar_quality_flag")
    i_flags = _first_index(conn, "INSERT INTO bar_quality_flag", kind="executemany")
    assert i_delete < i_flags  # the fresh set replaces, never accumulates onto


def test_changed_only_selects_symbol_with_new_answered_window():
    """A symbol whose 5m digests are unchanged is still re-derived when an
    answered ohlcv_request window was recorded after its last derivation."""
    expected = _expected_month_digests(_five_minute_fixture())
    current = {"SPY": [(start, digest) for start, (digest, _n) in expected.items()]}
    conn = FakeConn(bars={"SPY": _five_minute_fixture()}, current_digests=current)
    totals = _run(conn, changed_only=True)  # answered_since defaults False
    assert totals["unchanged"] == 1 and totals["derived"] == 0

    conn = FakeConn(
        bars={"SPY": _five_minute_fixture()},
        current_digests=current,
        answered_since=True,
    )
    totals = _run(conn, changed_only=True)
    assert totals["derived"] == 1 and totals["unchanged"] == 0


# ---------------------------------------------------------------------------
# Plan 185-18 task 1a: the coverage rule is the shared planner's, not a local
# copy (one definition of a missing bar for the fetcher, the derivation and the
# auditor).
# ---------------------------------------------------------------------------


def test_coverage_rule_comes_from_the_shared_planner():
    from services import bar_derivation

    assert bar_derivation.AnsweredWindows is gap_plan.AnsweredWindows
    assert set(bar_derivation.ANSWERED_OUTCOMES) == {"bars", "no_data"}


def test_answered_windows_sql_parameterizes_the_route():
    """route/what_to_show reach the query as parameters ($3/$4), so D-20's
    every-configured-route-answered rule widens coverage without SQL edits."""
    from services import bar_derivation

    sql = bar_derivation._SELECT_ANSWERED_WINDOWS_SQL
    assert "r.route = $3" in sql
    assert "r.what_to_show = $4" in sql
