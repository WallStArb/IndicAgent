"""Unit tests for the shared causal_expanding_rank helper. CI-clean: no DB, no network.

Moved out of test_regime_signals_breadth_vol.py when the causal-rank logic was extracted
into its own shared module (todo 092, 2026-07-24) so curve_credit.py could reuse it too.
"""

from __future__ import annotations

import math
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.stats

sys.path.insert(0, str(Path(__file__).parents[2]))

from src.intelligence.regime_signals.causal_rank import causal_expanding_rank


def _reference_causal_rank(values: list[float]) -> list[float]:
    """Independent oracle for causal_expanding_rank, used ONLY in this test file.

    Deliberately NOT the bisect-based implementation under test (that would make the
    equivalence check circular) -- uses scipy.stats.rankdata as an unrelated, independently
    correct rank primitive instead. For each position, the rank of the newest value within
    {all PRIOR valid values, itself} under scipy's 'average' tie method equals
    1 + (left+right)/2 where left/right are counts of prior values strictly-less-than/
    less-or-equal-to the new value -- so (scipy_rank - 1) / n_prior reproduces
    causal_rank.py's own documented formula via a completely different code path. Not
    optimized: this is a correctness oracle, not a candidate for production use.
    """
    out: list[float] = []
    window: list[float] = []
    for val in values:
        if math.isnan(val):
            out.append(float("nan"))
            continue
        if not window:
            out.append(1.0)
        else:
            ranks = scipy.stats.rankdata(window + [val], method="average")
            out.append((ranks[-1] - 1.0) / len(window))
        window.append(val)
    return out


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

    def test_matches_independent_oracle_with_ties_and_nans(self):
        """Stricter regression-lock than the property tests above: exact numeric equality
        against an independently-implemented oracle (see _reference_causal_rank), across
        randomized cases that deliberately include tied values and NaN runs -- the two
        edge cases most likely to silently diverge under an implementation swap. This test
        is expected to PASS against the current implementation (it is not the failing test
        for the performance fix below) -- it exists to pin the exact contract before the
        implementation is replaced with an O(n log n) version, so any behavioral drift in
        that rewrite is caught here rather than downstream in market_regimes labels.
        """
        rng = np.random.default_rng(42)
        for trial in range(20):
            n = rng.integers(5, 150)
            # Draw from a small discrete set to force real ties, not just float coincidence.
            values = rng.choice([1.0, 2.0, 2.0, 3.0, 3.0, 3.0, 4.0, 5.0], size=n).astype(float)
            # Sprinkle in some NaNs.
            nan_mask = rng.random(n) < 0.15
            values[nan_mask] = float("nan")

            expected = _reference_causal_rank(values.tolist())
            actual = causal_expanding_rank(pd.Series(values)).tolist()

            for i, (e, a) in enumerate(zip(expected, actual, strict=True)):
                if math.isnan(e):
                    assert math.isnan(a), f"trial {trial} pos {i}: expected NaN, got {a}"
                else:
                    assert math.isclose(
                        e, a, rel_tol=1e-12, abs_tol=1e-12
                    ), f"trial {trial} pos {i}: expected {e}, got {a}"

    def test_scales_near_linearithmic_not_quadratic(self):
        """The actual defect this module carried until 2026-08-21: causal_expanding_rank was
        O(n^2) (list + bisect.insort), fine at production's current daily-macro-series scale
        (~150s for the whole cross_sectional_regime_model.py batch step, corpus-wide) but
        catastrophic when reused against intraday series -- confirmed live via a 5m-timeframe
        analysis script (per_symbol_regime_candidates_stage3_falsification.py, ~392K
        rows/symbol) still running after 8+ hours, further multiplied by its own 200x
        null-arm replicate loop.

        Deliberately NOT an absolute wall-clock threshold (e.g. "must finish in 0.15s") --
        a first version of this test used one and was too fragile: this machine's own
        median-of-5 runtime at n=100,000 is a stable ~0.10s, but a single unlucky sample can
        spike past 0.18s from ordinary OS/GC jitter alone (measured directly, 2026-08-21),
        and CI runners are typically slower/noisier than a dedicated dev machine on top of
        that -- an absolute-time assertion would be a recurring source of unrelated CI
        flakiness (a real risk class this project's own memory calls out: "configured but
        never run" is one failure mode, but a flaky gate that trains people to ignore CI
        failures is arguably worse).

        Instead, this asserts the SHAPE of the scaling curve, which is invariant to how fast
        the machine is: time a 5x-larger input against a smaller one and check the ratio.
        O(n log n) predicts ~5 * (log(100k)/log(20k)) =~ 5.8x; O(n^2) predicts 5^2 = 25x.
        Empirically (2026-08-21, this implementation): 6.11x observed. The retired O(n^2)
        implementation measured 19.62x under the identical harness -- a clean, wide
        separation. 10x sits with real margin on both sides regardless of absolute hardware
        speed. Each measurement takes the median of 5 samples (not a single draw) to further
        damp one-off scheduling noise.
        """

        def _median_time(n: int) -> float:
            rng = np.random.default_rng(3)
            series = pd.Series(rng.normal(size=n))
            samples = []
            for _ in range(5):
                t0 = time.perf_counter()
                causal_expanding_rank(series)
                samples.append(time.perf_counter() - t0)
            return statistics.median(samples)

        n_small, n_large = 20_000, 100_000
        time_small = _median_time(n_small)
        time_large = _median_time(n_large)
        ratio = time_large / time_small

        assert ratio < 10.0, (
            f"causal_expanding_rank scaled {ratio:.2f}x when input grew "
            f"{n_large / n_small:.0f}x (n={n_small}->{n_large}) -- that shape is consistent "
            "with O(n^2), not O(n log n); see this test's docstring for the empirical "
            "baseline separating the two"
        )
