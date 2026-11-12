"""rank_float64 pins float64 ranks whatever dtype scipy's rankdata returns for float32 input."""

from __future__ import annotations

import numpy as np

from src.intelligence.statistics.ic_math import rank_float64


def test_float32_input_gives_float64_ranks():
    """scipy 1.18 ranks float32 input in float32 (1.17 returned float64)."""
    x = np.array([[3.0, np.nan], [1.0, 2.0], [3.0, 5.0], [2.0, 2.0]], dtype=np.float32)
    ranks = rank_float64(x, axis=0, nan_policy="omit")
    assert ranks.dtype == np.float64
    assert ranks[:, 0].tolist() == [3.5, 1.0, 3.5, 2.0]
