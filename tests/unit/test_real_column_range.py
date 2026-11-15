"""Unit tests for src/core/real_column_range.py (float4 clamp)."""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.core.real_column_range import (  # noqa: E402
    REAL_MAX_MAGNITUDE,
    REAL_MIN_MAGNITUDE,
    clamp_to_real_range,
)


class TestClampToRealRange:
    """todo 312: an HMM posterior probability underflowing float4's representable range
    made Postgres reject the write outright rather than round it -- these are the pure
    boundary-condition tests for the clamp that fixes it."""

    def test_underflowing_positive_value_clamps_to_zero(self) -> None:
        assert clamp_to_real_range(1e-50) == 0.0

    def test_underflowing_negative_value_clamps_to_zero(self) -> None:
        assert clamp_to_real_range(-1e-50) == 0.0

    def test_smallest_representable_subnormal_passes_through_unchanged(self) -> None:
        assert clamp_to_real_range(REAL_MIN_MAGNITUDE) == REAL_MIN_MAGNITUDE

    def test_overflowing_positive_value_clamps_to_real_max(self) -> None:
        assert clamp_to_real_range(1e50) == REAL_MAX_MAGNITUDE

    def test_overflowing_negative_value_clamps_to_negative_real_max(self) -> None:
        assert clamp_to_real_range(-1e50) == -REAL_MAX_MAGNITUDE

    def test_ordinary_probability_passes_through_unchanged(self) -> None:
        assert clamp_to_real_range(0.5) == 0.5

    def test_exact_zero_passes_through_unchanged(self) -> None:
        assert clamp_to_real_range(0.0) == 0.0

    def test_none_passes_through_unchanged(self) -> None:
        assert clamp_to_real_range(None) is None

    def test_nan_passes_through_unchanged(self) -> None:
        result = clamp_to_real_range(float("nan"))
        assert result != result  # NaN != NaN is the only valid NaN check

    def test_infinity_passes_through_unchanged(self) -> None:
        assert clamp_to_real_range(float("inf")) == float("inf")

    def test_non_float_value_passes_through_unchanged(self) -> None:
        assert clamp_to_real_range("trending_up") == "trending_up"
        assert clamp_to_real_range(5) == 5
