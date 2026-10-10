"""Bar load engine no-drop semantics (todo 528 R1): extended and first-writer-held
rows are archived raw, never dropped; the split counts are exact."""

from __future__ import annotations

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
    def __init__(self, rows: list):
        self._rows = rows

    def execute(self, *args, **kwargs) -> None: ...

    def fetchall(self) -> list:
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *args) -> bool:
        return False


class _FakeConn:
    def __init__(self, stored: list = None):
        self._stored = stored or []
        self.transactions = 0

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._stored)

    class _Tx:
        def __enter__(self):
            return self

        def __exit__(self, *args) -> bool:
            return False

    def transaction(self) -> _FakeConn._Tx:
        self.transactions += 1
        return self._Tx()


def test_archive_frame_to_tuples_carries_source_and_null_base() -> None:
    rows = archive_frame_to_tuples(
        _frame(["2026-10-09 13:30:00"]), "SPY", source="alpaca", timeframe="5m"
    )
    assert rows == [
        (
            pd.Timestamp("2026-10-09 13:30:00", tz="UTC").to_pydatetime(),
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


def test_split_series_separates_new_held_extended() -> None:
    frame = _frame(
        [
            "2026-10-09 13:30:00",
            "2026-10-09 13:35:00",
            "2026-10-09 12:00:00",  # pre-market: extended
        ]
    )
    conn = _FakeConn()
    new, held, extended = split_series(conn, "SPY", "5m", frame)
    assert len(new) == 2 and len(held) == 0 and len(extended) == 1


def test_split_series_holds_first_writer_rows() -> None:
    frame = _frame(["2026-10-09 13:30:00", "2026-10-09 13:35:00"])
    stored_stamp = pd.Timestamp("2026-10-09 13:30:00", tz="UTC").to_pydatetime()

    class _StoredConn(_FakeConn):
        def cursor(self) -> _FakeCursor:
            return _FakeCursor([(stored_stamp,)])

    new, held, extended = split_series(_StoredConn(), "SPY", "5m", frame)
    assert len(new) == 1 and len(held) == 1 and len(extended) == 0


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
