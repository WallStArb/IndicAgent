"""Unit tests for ops_lookahead_horizon_response.py's stride correction (todo 146).

The diagnostic's original Fisher-z CI was computed on raw overlapping-window observations
(consecutive forward returns at horizon h overlap by h-1 bars and are serially dependent),
understating its own half-width -- flagged by Fable 5's review of the todo-146 full-corpus
run. Fix mirrors ic_engine.py's production `scale_stride = max(subsample_min_stride,
lookahead_bars)` discipline. No DB, no asyncio -- pure function + CLI parsing tests only.
"""

from __future__ import annotations

import sys

from scripts.ops.alpha.ops_lookahead_horizon_response import _parse_args, _stride_for_horizon


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
