"""Unit tests for scripts/analysis/per_symbol_regime_candidates_stage2_orthogonality.py
(todos 303/304 Stage 2). Synthetic data only -- no DB, no live regime_writer/regime_
volatility dependency, matching test_per_symbol_regime_candidates_stage3_falsification.py's
convention (this script's sibling in the shared Stage 2/3 mechanism).
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from scripts.analysis.per_symbol_regime_candidates_stage2_orthogonality import (
    _AUTOCORR_LAG,
    _AUTOCORR_WINDOW,
    _compute_candidates,
    _rank_of_zscore,
    _rolling_autocorr,
)


def _make_synthetic_ohlcv(rng: np.random.Generator, n: int, sigma: float) -> pd.DataFrame:
    """Shared synthetic-OHLCV builder for this file's tests -- a geometric random walk
    (never negative, matches real close-price behavior). Callers that only need the log
    returns (what every _compute_candidates rolling window actually operates on) derive
    them via np.log(df["close"]).diff(), same as production's own _compute_candidates.
    """
    close = pd.Series(np.exp(np.cumsum(rng.normal(0, sigma, size=n))) * 100)
    volume = pd.Series(rng.integers(1000, 100_000, size=n)).astype(float)
    return pd.DataFrame({"close": close, "volume": volume})


def _reference_rolling_autocorr(series: pd.Series, window: int, lag: int) -> pd.Series:
    """Independent oracle for the rolling lag-k autocorrelation, used ONLY in this test
    file. Deliberately the SAME per-window-Series.autocorr() shape the retired
    implementation used (not the vectorized replacement under test) -- this is what
    stage2's rolling autocorr is documented to compute, so this oracle pins that contract
    independently of whichever internal formula the production code uses to get there.
    """
    return series.rolling(window=window, min_periods=window).apply(
        lambda w: pd.Series(w).autocorr(lag=lag), raw=False
    )


class TestRollingAutocorr:
    def test_matches_reference_oracle(self):
        """_rolling_autocorr must be exactly reproducible via the reference per-window
        Series.autocorr() oracle -- the contract the vectorized rewrite must preserve
        bit-for-bit, since this feeds a real falsification test (Stage 3) whose numbers
        this project treats as evidence, not just a diagnostic plot.
        """
        rng = np.random.default_rng(17)
        df = _make_synthetic_ohlcv(rng, n=500, sigma=0.01)
        log_ret = np.log(df["close"]).diff()

        expected = _reference_rolling_autocorr(log_ret, window=_AUTOCORR_WINDOW, lag=_AUTOCORR_LAG)
        actual = _rolling_autocorr(log_ret, window=_AUTOCORR_WINDOW, lag=_AUTOCORR_LAG)

        pd.testing.assert_series_equal(expected, actual, check_names=False)

    def test_completes_much_faster_than_a_per_window_python_callback_would(self):
        """The actual defect this function carried until this fix: it used
        `.rolling().apply(lambda w: pd.Series(w).autocorr(lag=1), raw=False)` -- a
        per-window Python callback that measured 34.0s for a single 392K-row symbol
        (2026-08-22 benchmark on this machine), the dominant cost in
        _compute_candidates (which itself sits in the hot path of Stage 3's 200x
        null-arm falsification loop -- todos 303/304's actual runtime bottleneck, not
        causal_expanding_rank's already-fixed O(n^2)).

        Deliberately benchmarks _rolling_autocorr in isolation, not the full
        _compute_candidates (an earlier version of this test did that and paid ~1.5s of
        unrelated Hurst-rolling-apply cost on every CI run for a test nominally about
        one rolling-window call -- fixed by extracting _rolling_autocorr as its own
        testable unit).

        Threshold learned from an earlier mistake the same day (see causal_rank.py's own
        test history): don't pick a number close to a single calibration run. Real
        multi-sample data at n=100,000, this machine (2026-08-22), isolated function
        only (not the full _compute_candidates, whose Hurst component this test no
        longer pays for): OLD implementation (per-window callback, whole-function
        measurement before the extraction) had an observed floor around 8.8s. NEW
        implementation (this fix) measured a stable 0.0095-0.0105s across 8 samples.
        1.0s leaves ~100x margin above the new implementation's observed ceiling and
        sits ~9x below the old implementation's observed floor -- a regression back to
        the per-window-callback shape would blow straight through this, not brush
        against it.
        """
        rng = np.random.default_rng(11)
        df = _make_synthetic_ohlcv(rng, n=100_000, sigma=0.001)
        log_ret = np.log(df["close"]).diff()

        t0 = time.perf_counter()
        _rolling_autocorr(log_ret, window=_AUTOCORR_WINDOW, lag=_AUTOCORR_LAG)
        elapsed = time.perf_counter() - t0

        assert elapsed < 1.0, (
            f"_rolling_autocorr took {elapsed:.3f}s for n=100,000 -- see this test's "
            "docstring for the empirical baseline separating the vectorized "
            "implementation from the retired per-window-callback one"
        )

    def test_raises_when_lag_at_least_window_instead_of_silently_returning_all_nan(self):
        """Found by /code-review 2026-08-22: `pd.Series.rolling(window=0, ...)` silently
        returns an all-NaN series with no exception (confirmed empirically) -- so
        lag >= window (effective_window <= 0) would be a silent-wrong-answer failure
        mode, not a loud crash, if this function's inputs ever changed from today's
        hardcoded-safe _AUTOCORR_WINDOW=20/_AUTOCORR_LAG=1. Explicit guard converts that
        into a real ValueError instead.
        """
        series = pd.Series(np.random.default_rng(1).normal(size=20))

        with pytest.raises(ValueError, match="lag.*must be < window"):
            _rolling_autocorr(series, window=5, lag=5)

        with pytest.raises(ValueError, match="lag.*must be < window"):
            _rolling_autocorr(series, window=5, lag=8)


class TestComputeCandidatesAutocorrRank:
    def test_autocorr_component_matches_reference_oracle_through_full_pipeline(self):
        """End-to-end check that _compute_candidates wires _rolling_autocorr into the
        same _rank_of_zscore pipeline as every other candidate -- TestRollingAutocorr
        above already pins the raw-autocorr contract in isolation; this confirms the
        wiring, not the math a second time.
        """
        rng = np.random.default_rng(17)
        df = _make_synthetic_ohlcv(rng, n=500, sigma=0.01)
        log_ret = np.log(df["close"]).diff()

        reference_autocorr_raw = _reference_rolling_autocorr(
            log_ret, window=_AUTOCORR_WINDOW, lag=_AUTOCORR_LAG
        )
        expected = _rank_of_zscore(reference_autocorr_raw)
        actual = _compute_candidates(df)["autocorr_rank"]

        pd.testing.assert_series_equal(expected, actual, check_names=False)
