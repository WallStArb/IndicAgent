"""ops_export_known_answer_fixtures: the fixture CSVs keep their plan-08 `source` column.

Since the 191-14 swap the canonical table carries (vendor, kind); the exporter selects the
pair and renders the legacy label so the fixture shape (header and values) is unchanged.
"""

from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.ops.bars.ops_export_known_answer_fixtures import _write_cursor_rows


class _FakeCursor:
    """A cursor over fixed rows with a psycopg-shaped description."""

    def __init__(self, columns: list[str], rows: list[tuple]):
        self.description = [SimpleNamespace(name=name, type_code=None) for name in columns]
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


_COLS_SHAPE = [
    "timestamp",
    "symbol",
    "timeframe",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "vendor",
    "kind",
    "base",
    "price_sanity_status",
]


def test_vendor_kind_collapse_keeps_the_source_column(tmp_path: Path) -> None:
    cur = _FakeCursor(
        _COLS_SHAPE,
        [
            ("2024-01-02", "SPY", "1d", 1.0, 2.0, 0.5, 1.5, 100, "ibkr", "named", None, None),
            ("2024-01-03", "SPY", "1d", 1.0, 2.0, 0.5, 1.5, 100, "alpaca", "sip_rth", None, None),
        ],
    )
    path = tmp_path / "out.csv"
    assert _write_cursor_rows(cur, path) == 2  # type: ignore[arg-type]
    with path.open() as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == [
        "timestamp",
        "symbol",
        "timeframe",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "source",
        "base",
        "price_sanity_status",
    ]
    assert [row[8] for row in rows[1:]] == ["ibkr_named", "alpaca"]


def test_a_cursor_without_the_pair_writes_through_unchanged(tmp_path: Path) -> None:
    cur = _FakeCursor(["symbol", "timestamp"], [("SPY", "2024-01-02")])
    path = tmp_path / "out.csv"
    _write_cursor_rows(cur, path)  # type: ignore[arg-type]
    with path.open() as handle:
        rows = list(csv.reader(handle))
    assert rows == [["symbol", "timestamp"], ["SPY", "2024-01-02"]]


def test_a_separated_or_lone_pair_column_fails_loud(tmp_path: Path) -> None:
    """191-15 review P3-5: the collapse must not ride on column adjacency; a pair-carrying
    cursor that does not match _COLS by name raises instead of silently writing a
    differently-shaped fixture."""
    separated = _FakeCursor(
        ["timestamp", "symbol", "vendor", "kind", "base"],
        [("2024-01-02", "SPY", "ibkr", "named", None)],
    )
    with pytest.raises(ValueError, match="_COLS"):
        _write_cursor_rows(separated, tmp_path / "separated.csv")  # type: ignore[arg-type]
    lone = _FakeCursor(["symbol", "vendor"], [("SPY", "ibkr")])
    with pytest.raises(ValueError, match="_COLS"):
        _write_cursor_rows(lone, tmp_path / "lone.csv")  # type: ignore[arg-type]


def test_an_unmapped_pair_fails_loud(tmp_path: Path) -> None:
    cur = _FakeCursor(
        _COLS_SHAPE,
        [
            (
                "2024-01-02",
                "SPY",
                "1d",
                1.0,
                2.0,
                0.5,
                1.5,
                100,
                "ibkr",
                "smart_adjusted",
                None,
                None,
            )
        ],
    )
    with pytest.raises(KeyError, match="smart_adjusted"):
        _write_cursor_rows(cur, tmp_path / "out.csv")  # type: ignore[arg-type]
