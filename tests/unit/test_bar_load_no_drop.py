"""Bar load engine no-drop semantics (todo 528 R1): extended and first-writer-held
rows are archived raw, never dropped; the split counts are exact."""

from __future__ import annotations

import pandas as pd
import pytest

from services import bar_load
from services.bar_load import LoadPolicy, _archive_rows, load_series

POLICY = LoadPolicy(vendor="alpaca", timeframe="5m", caller="test-load")


def _frame(rows: list[tuple[str, bool]]) -> pd.DataFrame:
    """(iso stamp, in_grid) rows -> canonical frame; grid stamps are 13:30/13:35 UTC."""
    stamps = [pd.Timestamp(t, tz="UTC") for t, _ in rows]
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


def test_archive_rows_sends_vendor_tuples_and_skips_empty(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_insert(cur, rows, *, caller):
        calls.extend(rows)
        return len(rows)

    monkeypatch.setattr(bar_load, "insert_fetched_archive_rows", fake_insert)
    conn = _FakeConn()
    assert _archive_rows(conn, POLICY, "SPY", _frame([])[:0]) == 0
    assert calls == [] and conn.transactions == 0

    frame = _frame([("2026-10-09 13:30:00", True), ("2026-10-09 13:35:00", True)])
    archived = _archive_rows(conn, POLICY, "SPY", frame)
    assert archived == 2 and len(calls) == 2
    ts, symbol, timeframe, o, h, low, c, v, source, base = calls[0]
    assert (symbol, timeframe, source, base) == ("SPY", "5m", "alpaca", None)
    assert (o, h, low, c, v) == (1.0, 1.0, 1.0, 1.0, 100)


def test_load_series_dry_run_splits_extended_and_plans_grid_rows() -> None:
    # two in-grid rows (13:30/13:35 UTC RTH), one extended row (17:00 UTC = post-close)
    frame = _frame(
        [
            ("2026-10-09 13:30:00", True),
            ("2026-10-09 13:35:00", True),
            ("2026-10-09 12:00:00", False),
        ]
    )
    conn = _FakeConn()
    planned, skipped_stored, dropped_extended = load_series(
        conn, POLICY, "SPY", frame, params=None, write=False
    )
    assert (planned, skipped_stored, dropped_extended) == (2, 0, 1)


def test_load_series_counts_first_writer_held_rows(monkeypatch) -> None:
    frame = _frame([("2026-10-09 13:30:00", True), ("2026-10-09 13:35:00", True)])
    stored_stamp = pd.Timestamp("2026-10-09 13:30:00", tz="UTC").to_pydatetime()

    class _StoredConn(_FakeConn):
        def cursor(self) -> _FakeCursor:
            return _FakeCursor([(stored_stamp,)])

    conn = _StoredConn()
    planned, skipped_stored, dropped_extended = load_series(
        conn, POLICY, "SPY", frame, params=None, write=False
    )
    assert (planned, skipped_stored, dropped_extended) == (1, 1, 0)


def test_empty_grid_frame_still_archives_extended_when_writing(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_insert(cur, rows, *, caller):
        calls.extend(rows)
        return len(rows)

    monkeypatch.setattr(bar_load, "insert_fetched_archive_rows", fake_insert)
    frame = _frame([("2026-10-09 12:00:00", False)])
    conn = _FakeConn()
    applied, skipped_stored, dropped_extended = load_series(
        conn, POLICY, "SPY", frame, params=None, write=True
    )
    assert (applied, skipped_stored, dropped_extended) == (0, 0, 1)
    assert len(calls) == 1 and calls[0][1] == "SPY"


def test_archive_rows_requires_write(monkeypatch) -> None:
    monkeypatch.setattr(
        bar_load,
        "insert_fetched_archive_rows",
        lambda *a, **k: pytest.fail("archive write without --apply"),
    )
    frame = _frame([("2026-10-09 13:30:00", True), ("2026-10-09 12:00:00", False)])
    conn = _FakeConn()
    planned, skipped_stored, dropped_extended = load_series(
        conn, POLICY, "SPY", frame, params=None, write=False
    )
    assert (planned, skipped_stored, dropped_extended) == (1, 0, 1)
