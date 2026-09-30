"""Masked-slot baseline (todo 462, plan 185-12): parameters, totals and the 15m-only guard."""

from __future__ import annotations

import pytest

from scripts.ops.bars import ops_masked_slot_baseline as baseline


class _Cursor:
    def __init__(self, fetchone=None, fetchall=None) -> None:
        self._fetchone = fetchone
        self._fetchall = fetchall or []
        self.calls: list[tuple[str, dict]] = []

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: dict) -> None:
        self.calls.append((sql, params))

    def fetchone(self):
        return self._fetchone

    def fetchall(self):
        return self._fetchall


class _Conn:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _Cursor:
        return self._cursor


def test_params_bin_a_year_at_the_15m_grid():
    params = baseline._params("15m", 2025)
    assert params == {
        "coarse": "15m",
        "bin": "15 minutes",
        "start": "2025-01-01",
        "end": "2026-01-01",
    }


@pytest.mark.parametrize("coarse", ["1h", "5m", "1d"])
def test_only_15m_is_supported(coarse):
    with pytest.raises(ValueError, match="15m"):
        baseline._params(coarse, 2025)


def test_masked_by_year_reads_one_row_per_year():
    cursor = _Cursor(fetchone=(120, 7, 2, 5_000))
    rows = baseline.masked_by_year(_Conn(cursor), "15m", [2024, 2025])
    assert rows == [
        {
            "year": 2024,
            "synthetic_rows": 120,
            "masked_slots": 7,
            "symbols": 2,
            "hidden_volume": 5_000,
        },
        {
            "year": 2025,
            "synthetic_rows": 120,
            "masked_slots": 7,
            "symbols": 2,
            "hidden_volume": 5_000,
        },
    ]
    assert [call[1]["start"] for call in cursor.calls] == ["2024-01-01", "2025-01-01"]


def test_whole_year_masked_passes_the_threshold_and_orders_by_count():
    cursor = _Cursor(fetchall=[("CCJ", 6464), ("COP", 6464)])
    names = baseline.whole_year_masked(_Conn(cursor), "15m", 2025, 6000)
    assert names == [("CCJ", 6464), ("COP", 6464)]
    assert cursor.calls[0][1]["min_slots"] == 6000
    assert cursor.calls[0][1]["start"] == "2025-01-01"


def test_totals_sum_across_years():
    rows = [
        {"year": 2024, "masked_slots": 10, "hidden_volume": 100},
        {"year": 2025, "masked_slots": 0, "hidden_volume": 0},
        {"year": 2026, "masked_slots": 5, "hidden_volume": 50},
    ]
    assert baseline.totals(rows) == {
        "masked_slots": 15,
        "hidden_volume": 150,
        "years_with_masked_slots": 2,
    }


def test_the_sql_reads_the_tradeable_view_for_5m_and_never_the_raw_5m_table():
    # The raw table is read only for the coarse synthetic rows under test.
    assert "market_data_ohlcv_tradeable" in baseline._MASKED_BY_YEAR_SQL
    assert "timeframe = '5m'" in baseline._MASKED_BY_YEAR_SQL
    assert "source = 'synthetic_fill'" in baseline._MASKED_BY_YEAR_SQL
