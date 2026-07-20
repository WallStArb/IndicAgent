"""Unit tests for ops_lookahead_horizon_response.py's stride correction (todo 146).

The diagnostic's original Fisher-z CI was computed on raw overlapping-window observations
(consecutive forward returns at horizon h overlap by h-1 bars and are serially dependent),
understating its own half-width -- flagged by Fable 5's review of the todo-146 full-corpus
run. Fix mirrors ic_engine.py's production `scale_stride = max(subsample_min_stride,
lookahead_bars)` discipline. No DB, no asyncio -- pure function + CLI parsing tests only.
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import patch

import pytest

from scripts.ops.alpha.ops_lookahead_horizon_response import (
    _fetch_all_symbols_horizon_rows,
    _parse_args,
    _stride_for_horizon,
)


class TestStrideForHorizon:
    def test_short_horizon_floored_at_min_stride(self):
        assert _stride_for_horizon(min_stride=5, horizon_bars=1) == 5

    def test_horizon_at_min_stride_boundary(self):
        assert _stride_for_horizon(min_stride=5, horizon_bars=5) == 5

    def test_long_horizon_exceeds_min_stride(self):
        assert _stride_for_horizon(min_stride=5, horizon_bars=60) == 60

    def test_custom_min_stride(self):
        assert _stride_for_horizon(min_stride=10, horizon_bars=6) == 10


class TestMinStrideCliFlag:
    def test_defaults_to_none(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog"])
        args = _parse_args()
        assert args.min_stride is None

    def test_accepts_value(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog", "--min-stride", "10"])
        args = _parse_args()
        assert args.min_stride == 10


class TestFetchAllSymbolsHorizonRowsConcurrency:
    @pytest.mark.asyncio
    async def test_fetches_all_symbols_concurrently(self):
        """Per-symbol fetches must overlap in time (asyncio.gather), not run one
        after another -- and pairing (symbol, rows) must survive gather's ordering
        guarantee (results ordered by input, not completion order)."""
        concurrent = 0
        max_concurrent = 0

        async def fake_fetch(pool, tf, symbol, vintage, horizons, max_bars_per_symbol):
            nonlocal concurrent, max_concurrent
            concurrent += 1
            max_concurrent = max(max_concurrent, concurrent)
            await asyncio.sleep(0.01)
            concurrent -= 1
            return [{"symbol": symbol}]

        with patch(
            "scripts.ops.alpha.ops_lookahead_horizon_response._fetch_horizon_response_rows",
            new=fake_fetch,
        ):
            result = await _fetch_all_symbols_horizon_rows(
                pool=None,
                tf="1h",
                symbols=["A", "B", "C"],
                vintage=None,
                horizons=(1, 2),
                max_bars_per_symbol=100,
            )

        assert max_concurrent > 1, "fetches ran sequentially, not concurrently"
        assert [symbol for symbol, _ in result] == ["A", "B", "C"]
        assert result[1][1] == [{"symbol": "B"}]
