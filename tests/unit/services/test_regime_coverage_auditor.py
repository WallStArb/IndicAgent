"""Unit tests for regime_coverage_auditor. CI-clean: no DB, no network."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parents[3]))

from services.regime_coverage_auditor import _fetch_coverage_gaps


def _mock_cursor(gap_rows: list[dict]) -> MagicMock:
    cur = MagicMock()
    cur.fetchall.return_value = gap_rows
    return cur


def test_no_gap_returns_empty_list():
    cur = _mock_cursor([])
    assert _fetch_coverage_gaps(cur) == []
    cur.execute.assert_called_once()


def test_gap_found_returns_symbol_list():
    cur = _mock_cursor(
        [
            {"symbol": "LQD", "total_rows": 100, "non_null_regime_rows": 0},
            {"symbol": "SPY", "total_rows": 200, "non_null_regime_rows": 0},
        ]
    )
    assert _fetch_coverage_gaps(cur) == ["LQD", "SPY"]
