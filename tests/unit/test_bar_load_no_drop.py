"""Bar load engine no-drop semantics (todo 528 R1): extended and rows another
source holds are archived raw, never dropped; a vendor's own canonical rows are
a no-op, never re-archived. The split counts are exact."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from services import bar_load
from services.bar_load import (
    LoadPolicy,
    archive_frame_to_tuples,
    archive_rows,
    load_series,
    split_series,
)

POLICY = LoadPolicy(vendor="alpaca", timeframe="5m", caller="test-load")


def _frame(rows: list[str]) -> pd.DataFrame:
    """ISO stamps -> canonical frame; grid stamps are 13:30/13:35 UTC (RTH)."""
    stamps = [pd.Timestamp(t, tz="UTC") for t in rows]
    return pd.DataFrame(
        {
            "t": stamps,
            "o": [1.0] * len(rows),
            "h": [1.0] * len(rows),
            "l": [1.0] * len(rows),
            "c": [1.0] * len(rows),
            "v": [100] * len(rows),
        }
    )


class _FakeCursor:
    def __init__(self, queries: dict[str, list]):
        self._queries = queries

    def execute(self, sql: str, args=None) -> None:
        self._rows = [
            (stamp,) for stamp in self._queries.get("other" if "source <>" in sql else "all", [])
        ]

    def fetchall(self) -> list:
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *args) -> bool:
        return False


class _FakeConn:
    def __init__(self, all_stored: list = None, other_stored: list = None):
        self._queries = {"all": all_stored or [], "other": other_stored or []}
        self.transactions = 0

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._queries)

    class _Tx:
        def __enter__(self):
            return self

        def __exit__(self, *args) -> bool:
            return False

    def transaction(self) -> _FakeConn._Tx:
        self.transactions += 1
        return self._Tx()


def _stamp(iso: str) -> datetime:
    return pd.Timestamp(iso, tz="UTC").to_pydatetime()


def test_archive_frame_to_tuples_carries_source_and_null_base() -> None:
    rows = archive_frame_to_tuples(
        _frame(["2026-10-09 13:30:00"]), "SPY", source="alpaca", timeframe="5m"
    )
    assert rows == [
        (
            _stamp("2026-10-09 13:30:00"),
            "SPY",
            "5m",
            1.0,
            1.0,
            1.0,
            1.0,
            100,
            "alpaca",
            None,
        )
    ]


def test_archive_rows_chunks_and_skips_empty(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_insert(cur, rows, *, caller, params=None):
        calls.extend(rows)
        return len(rows)

    monkeypatch.setattr(bar_load, "insert_fetched_archive_rows", fake_insert)
    conn = _FakeConn()
    assert archive_rows(conn, [], caller="test") == 0
    assert calls == [] and conn.transactions == 0

    rows = archive_frame_to_tuples(
        _frame(["2026-10-09 13:30:00", "2026-10-09 13:35:00"]),
        "SPY",
        source="alpaca",
        timeframe="5m",
    )
    assert archive_rows(conn, rows, caller="test") == 2
    assert len(calls) == 2 and conn.transactions == 1


def test_split_series_four_way() -> None:
    # 13:30 nobody holds (new), 13:35 ibkr holds (held), 14:00 alpaca holds
    # itself (own), 12:00 pre-market (extended)
    frame = _frame(
        ["2026-10-09 13:30:00", "2026-10-09 13:35:00", "2026-10-09 14:00:00", "2026-10-09 12:00:00"]
    )
    all_stored = [_stamp("2026-10-09 13:35:00"), _stamp("2026-10-09 14:00:00")]
    other_stored = [_stamp("2026-10-09 13:35:00")]
    new, held, own, extended = split_series(
        _FakeConn(all_stored, other_stored), "SPY", "5m", frame, vendor="alpaca"
    )
    assert len(new) == 1 and len(held) == 1 and len(own) == 1 and len(extended) == 1


def test_split_series_own_rows_are_never_archived() -> None:
    # a rerun: every in-grid stamp is alpaca's own canonical answer
    frame = _frame(["2026-10-09 13:30:00", "2026-10-09 13:35:00"])
    all_stored = [_stamp("2026-10-09 13:30:00"), _stamp("2026-10-09 13:35:00")]
    new, held, own, extended = split_series(
        _FakeConn(all_stored, []), "SPY", "5m", frame, vendor="alpaca"
    )
    assert len(new) == 0 and len(held) == 0 and len(own) == 2 and len(extended) == 0


def test_load_series_dry_run_splits_and_writes_nothing(monkeypatch) -> None:
    monkeypatch.setattr(
        bar_load,
        "insert_fetched_archive_rows",
        lambda *a, **k: pytest.fail("archive write without --apply"),
    )
    frame = _frame(["2026-10-09 13:30:00", "2026-10-09 13:35:00", "2026-10-09 12:00:00"])
    conn = _FakeConn()
    planned, skipped_stored, dropped_extended = load_series(
        conn, POLICY, "SPY", frame, params=None, write=False
    )
    assert (planned, skipped_stored, dropped_extended) == (2, 0, 1)


def test_load_series_archives_extended_when_grid_is_empty(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_insert(cur, rows, *, caller, params=None):
        calls.extend(rows)
        return len(rows)

    monkeypatch.setattr(bar_load, "insert_fetched_archive_rows", fake_insert)
    frame = _frame(["2026-10-09 12:00:00"])
    conn = _FakeConn()
    applied, skipped_stored, dropped_extended = load_series(
        conn, POLICY, "SPY", frame, params=None, write=True
    )
    assert (applied, skipped_stored, dropped_extended) == (0, 0, 1)
    assert len(calls) == 1 and calls[0][1] == "SPY"
