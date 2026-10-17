"""ops_export_known_answer_fixtures: the fixture CSVs keep their plan-08 `source` column.

Since the 191-14 swap the canonical table carries (vendor, kind); the exporter selects the
pair and renders the legacy label so the fixture shape (header and values) is unchanged.
"""

from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace

from scripts.ops.bars.ops_export_known_answer_fixtures import _write_cursor_rows


class _FakeCursor:
    """A cursor over fixed rows with a psycopg-shaped description."""

    def __init__(self, columns: list[str], rows: list[tuple]):
        self.description = [SimpleNamespace(name=name, type_code=None) for name in columns]
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


def test_vendor_kind_collapse_keeps_the_source_column(tmp_path: Path) -> None:
    cur = _FakeCursor(
        [
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
        ],
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
    cur = _FakeCursor(["symbol", "vendor"], [("SPY", "ibkr")])
    path = tmp_path / "out.csv"
    _write_cursor_rows(cur, path)  # type: ignore[arg-type]
    with path.open() as handle:
        rows = list(csv.reader(handle))
    assert rows == [["symbol", "vendor"], ["SPY", "ibkr"]]


def test_an_unmapped_pair_fails_loud(tmp_path: Path) -> None:
    cur = _FakeCursor(["vendor", "kind"], [("ibkr", "smart_adjusted")])
    import pytest

    with pytest.raises(KeyError, match="smart_adjusted"):
        _write_cursor_rows(cur, tmp_path / "out.csv")  # type: ignore[arg-type]
