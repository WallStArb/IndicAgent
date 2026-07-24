"""Unit tests for the shared causal_expanding_rank helper. CI-clean: no DB, no network.

Moved out of test_regime_signals_breadth_vol.py when the causal-rank logic was extracted
into its own shared module (todo 092, 2026-07-24) so curve_credit.py could reuse it too.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[2]))

from src.intelligence.regime_signals.causal_rank import causal_expanding_rank


class TestCausalExpandingRank:
    def test_first_value_ranks_one(self):
        result = causal_expanding_rank(pd.Series([5.0, 1.0, 9.0]))
        assert result.iloc[0] == 1.0

    def test_causal_property_future_value_does_not_change_past_ranks(self):
        rng = np.random.default_rng(11)
        series_n = pd.Series(rng.normal(size=60))
        ranks_n = causal_expanding_rank(series_n)

        series_n1 = pd.concat([series_n, pd.Series([1000.0])], ignore_index=True)
        ranks_n1 = causal_expanding_rank(series_n1)

        assert np.allclose(ranks_n.to_numpy(), ranks_n1.iloc[:60].to_numpy())

    def test_nan_passthrough_does_not_pollute_sorted_window(self):
        series = pd.Series([1.0, float("nan"), 2.0, 3.0])
        result = causal_expanding_rank(series)
        assert math.isnan(result.iloc[1])
        # The value immediately after the NaN ranks against {1.0} only, not {1.0, NaN}.
        assert result.iloc[2] == 1.0

    def test_output_bounded_zero_to_one(self):
        rng = np.random.default_rng(5)
        series = pd.Series(rng.normal(size=200))
        result = causal_expanding_rank(series).dropna()
        assert (result >= 0.0).all()
        assert (result <= 1.0).all()
