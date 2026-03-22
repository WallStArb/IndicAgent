"""Unit tests for VIX context computation module.

Tests cover:
  - Happy path: sufficient bars → ready=True with correct level/z_score
  - Insufficient data paths (empty, < z_window)
  - Edge case: exactly z_window bars
  - Edge case: zero stddev (all same price) → z_score = 0.0
  - Custom z_window parameter
  - Manual z_score calculation match
  - Module purity check (no service/kafka imports)
"""

from __future__ import annotations

import math
import statistics
from collections import deque
from datetime import datetime, timezone

import pytest

from src.core.schemas.bar_message import BarMessage, SessionType


def _make_bar(close: float, ts_offset: int = 0) -> BarMessage:
    """Helper to create a minimal BarMessage with a given close price."""
    return BarMessage(
        ts=datetime(2026, 3, 22, 10, ts_offset % 60, 0, tzinfo=timezone.utc),
        symbol="VIX",
        tf="1m",
        open=close,
        high=close + 0.1,
        low=close - 0.1,
        close=close,
        volume=1000,
        source="ibkr_named",
        session_type=SessionType.RTH,
        gap_preceding=False,
    )


def _make_bars(close_prices: list[float]) -> deque:
    """Build a deque of BarMessage objects from a list of close prices."""
    return deque(_make_bar(price, i) for i, price in enumerate(close_prices))


class TestComputeVixContextHappyPath:
    """Test 1: 25 bars with known close prices → ready=True with correct fields."""

    def test_returns_ready_true_with_25_bars(self) -> None:
        from src.intelligence.context.vix_context import compute_vix_context

        closes = [15.0 + i * 0.1 for i in range(25)]
        bars = _make_bars(closes)

        result = compute_vix_context(bars)

        assert result["ready"] is True
        assert "level" in result
        assert "z_score" in result

    def test_level_equals_last_close(self) -> None:
        from src.intelligence.context.vix_context import compute_vix_context

        closes = [15.0 + i * 0.1 for i in range(25)]
        bars = _make_bars(closes)

        result = compute_vix_context(bars)

        # level must be the most recent close price
        assert result["level"] == round(closes[-1], 4)

    def test_returned_values_are_floats(self) -> None:
        from src.intelligence.context.vix_context import compute_vix_context

        closes = [20.0 + i * 0.5 for i in range(25)]
        bars = _make_bars(closes)

        result = compute_vix_context(bars)

        assert isinstance(result["level"], float)
        assert isinstance(result["z_score"], float)


class TestComputeVixContextInsufficientData:
    """Tests 2 & 3: empty deque and < z_window bars → ready=False."""

    def test_empty_deque_returns_not_ready(self) -> None:
        from src.intelligence.context.vix_context import compute_vix_context

        result = compute_vix_context(deque())

        assert result == {"ready": False}

    def test_19_bars_returns_not_ready(self) -> None:
        from src.intelligence.context.vix_context import compute_vix_context

        bars = _make_bars([15.0 + i for i in range(19)])

        result = compute_vix_context(bars)

        assert result == {"ready": False}

    def test_one_bar_returns_not_ready(self) -> None:
        from src.intelligence.context.vix_context import compute_vix_context

        bars = _make_bars([18.5])

        result = compute_vix_context(bars)

        assert result == {"ready": False}


class TestComputeVixContextEdgeCases:
    """Test 4: exactly z_window bars → ready=True."""

    def test_exactly_20_bars_returns_ready(self) -> None:
        from src.intelligence.context.vix_context import compute_vix_context

        bars = _make_bars([15.0 + i * 0.1 for i in range(20)])

        result = compute_vix_context(bars)

        assert result["ready"] is True

    def test_19_bars_not_ready_20_bars_ready_boundary(self) -> None:
        from src.intelligence.context.vix_context import compute_vix_context

        bars_19 = _make_bars([15.0] * 19)
        bars_20 = _make_bars([15.0] * 20)

        assert compute_vix_context(bars_19)["ready"] is False
        assert compute_vix_context(bars_20)["ready"] is True


class TestComputeVixContextZeroStddev:
    """Test 5: all same close price (stddev=0) → z_score=0.0 (not NaN/Inf)."""

    def test_constant_price_gives_zero_z_score(self) -> None:
        from src.intelligence.context.vix_context import compute_vix_context

        bars = _make_bars([20.0] * 25)

        result = compute_vix_context(bars)

        assert result["ready"] is True
        assert result["z_score"] == 0.0
        # Explicitly check no NaN or Inf
        assert not math.isnan(result["z_score"])
        assert not math.isinf(result["z_score"])


class TestComputeVixContextCustomWindow:
    """Test 6: custom z_window=10, 10 bars → ready=True."""

    def test_custom_z_window_10_with_10_bars(self) -> None:
        from src.intelligence.context.vix_context import compute_vix_context

        bars = _make_bars([15.0 + i * 0.2 for i in range(10)])

        result = compute_vix_context(bars, z_window=10)

        assert result["ready"] is True

    def test_custom_z_window_10_with_9_bars_not_ready(self) -> None:
        from src.intelligence.context.vix_context import compute_vix_context

        bars = _make_bars([15.0 + i * 0.2 for i in range(9)])

        result = compute_vix_context(bars, z_window=10)

        assert result["ready"] is False


class TestComputeVixContextManualCalculation:
    """Test 7: returned z_score matches manual calculation."""

    def test_z_score_matches_manual_formula(self) -> None:
        from src.intelligence.context.vix_context import compute_vix_context

        # Use a 20-element sequence with clear arithmetic progression
        closes = [10.0 + i * 0.5 for i in range(20)]
        bars = _make_bars(closes)

        result = compute_vix_context(bars, z_window=20)

        # Manual: z = (last - mean) / stdev over last 20 bars
        window = closes[-20:]
        mean = sum(window) / len(window)
        std = statistics.stdev(window)  # sample stdev
        expected_z = (window[-1] - mean) / std
        expected_level = round(closes[-1], 4)
        expected_z_rounded = round(expected_z, 4)

        assert result["level"] == pytest.approx(expected_level, abs=1e-6)
        assert result["z_score"] == pytest.approx(expected_z_rounded, abs=1e-6)

    def test_z_score_with_more_bars_uses_last_z_window(self) -> None:
        from src.intelligence.context.vix_context import compute_vix_context

        # 30 bars — only last 20 should be used for computation
        closes = [10.0 + i * 0.3 for i in range(30)]
        bars = _make_bars(closes)

        result = compute_vix_context(bars, z_window=20)

        window = closes[-20:]
        mean = sum(window) / len(window)
        std = statistics.stdev(window)
        expected_z = round((window[-1] - mean) / std, 4)

        assert result["z_score"] == pytest.approx(expected_z, abs=1e-6)


class TestComputeVixContextModulePurity:
    """Test 8: module has no imports from services/ or src/core/kafka_utils."""

    def test_no_service_layer_imports(self) -> None:
        import inspect

        import src.intelligence.context.vix_context as vix_module

        source = inspect.getsource(vix_module)

        assert "from services" not in source, "Module imports from services/ layer"
        assert "import services" not in source, "Module imports from services/ layer"

    def test_no_kafka_utils_imports(self) -> None:
        import inspect

        import src.intelligence.context.vix_context as vix_module

        source = inspect.getsource(vix_module)

        assert "kafka_utils" not in source, "Module imports kafka_utils"
        assert "from src.core.kafka" not in source, "Module imports from src.core.kafka"

    def test_no_settings_imports(self) -> None:
        import inspect

        import src.intelligence.context.vix_context as vix_module

        source = inspect.getsource(vix_module)

        assert "from src.config" not in source, "Module imports from src.config (Settings)"
        assert "import settings" not in source.lower(), "Module imports settings"
