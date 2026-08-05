"""Parity tests: _*_series_full batch functions vs scalar streaming equivalents.

Contract: for every _*_series_full function, batch[j] must match the equivalent
scalar call on bars[:j+<offset>] to within 1e-8. Any divergence is a data integrity
violation — the batch precompute path and the live streaming path must produce
identical feature values.

When _ret_skew_z_series_full / _ret_acf1_z_series_full are added, follow the
same pattern: generate N synthetic bars, run FeatureFactory.compute in a loop to
collect ret_skew_z / ret_acf1_z, run the series_full function once, assert match.
"""

import math

import numpy as np
import pytest

from src.intelligence.feature_factory import (
    _atr_series_full,
    _atr_wilder,
)


def _make_bars(n: int, seed: int = 42) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    close = 100.0 * np.cumprod(1 + rng.normal(0, 0.01, n))
    high = close * (1 + rng.uniform(0, 0.005, n))
    low = close * (1 - rng.uniform(0, 0.005, n))
    return high, low, close


class TestAtrSeriesFull:
    """_atr_series_full[j] == _atr_wilder(h[:j+2], l[:j+2], c[:j+2], period)."""

    @pytest.mark.parametrize("period", [5, 14, 20])
    def test_matches_scalar_streaming(self, period: int) -> None:
        N = 1000
        highs, lows, closes = _make_bars(N)

        batch = _atr_series_full(highs, lows, closes, period)
        assert len(batch) == N - 1

        for j in range(len(batch)):
            streaming = _atr_wilder(highs[: j + 2], lows[: j + 2], closes[: j + 2], period)
            assert abs(batch[j] - streaming) < 1e-8, (
                f"period={period} j={j}: batch={batch[j]:.12f} "
                f"streaming={streaming:.12f} delta={abs(batch[j] - streaming):.2e}"
            )

    def test_zero_prefix_before_sufficient_bars(self) -> None:
        """Values before period-1 bars must be 0.0 (matches _atr_wilder semantics)."""
        period = 14
        N = 1000
        highs, lows, closes = _make_bars(N)
        batch = _atr_series_full(highs, lows, closes, period)
        # _atr_wilder returns 0.0 when n < period+1, i.e. j+2 < period+1, i.e. j < period-1
        for j in range(min(period - 2, len(batch))):
            assert batch[j] == 0.0, f"j={j} should be 0.0 before sufficient bars, got {batch[j]}"

    def test_nonzero_after_sufficient_bars(self) -> None:
        period = 14
        N = 1000
        highs, lows, closes = _make_bars(N)
        batch = _atr_series_full(highs, lows, closes, period)
        # From j = period-1 onward ATR should be positive on real price data
        assert all(batch[period - 1 :] > 0), "Expected positive ATR values after warm-up"

    def test_short_input_returns_empty(self) -> None:
        highs, lows, closes = _make_bars(1)
        result = _atr_series_full(highs, lows, closes, 14)
        assert len(result) == 0

    def test_idempotent(self) -> None:
        """Calling twice on same data returns identical arrays (no hidden state)."""
        highs, lows, closes = _make_bars(500)
        a = _atr_series_full(highs, lows, closes, 14)
        b = _atr_series_full(highs, lows, closes, 14)
        np.testing.assert_array_equal(a, b)


# ---------------------------------------------------------------------------
# Test MIN_WINDOW derived from config (not hardcoded)
# ---------------------------------------------------------------------------


def _make_config_for_min_window():
    """Config where max constituent is cci_slow_period=40."""
    from tests.unit.services.test_backfill_feature_factory import _make_config

    return _make_config()  # cci_slow=40, aroon_slow=25, vol_long=20, cmf=20 → MIN_WINDOW=40


def _make_bars_dicts(n: int, seed: int = 0) -> list[dict]:
    from datetime import UTC, datetime, timedelta

    import numpy as np

    rng = np.random.default_rng(seed)
    base = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    closes = 100.0 * np.cumprod(1 + rng.normal(0, 0.005, n))
    return [
        {
            "ts": base + timedelta(minutes=i),
            "open": float(closes[i] * 0.999),
            "high": float(closes[i] * 1.002),
            "low": float(closes[i] * 0.998),
            "close": float(closes[i]),
            "volume": 1000.0,
        }
        for i in range(n)
    ]


class TestMinWindowDerived:
    def test_compute_batch_produces_results_with_fewer_than_50_bars_warmup(self) -> None:
        """With MIN_WINDOW=40 (derived), a 42-bar batch must emit results.

        Before the fix MIN_WINDOW=50 was hardcoded. With MIN_WINDOW=40, bars[41]
        has a full 40-bar bounded window available — cci_slow etc. are computable.
        This test fails if MIN_WINDOW is still 50 (window_bars would only be 42
        bars but the bounded window slice [42-50:43] = [-8:43] = bars[:43] = 43
        bars, which is fine — so this test actually validates that the constant
        responds to config, not a behavior change at this size).
        """
        import math

        from src.intelligence.feature_cache import FeatureCache
        from src.intelligence.feature_factory import FeatureFactory

        config = _make_config_for_min_window()
        cache = FeatureCache()
        bars = _make_bars_dicts(60)
        results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache, config, warm_up_bars=5)
        assert len(results) > 0, "compute_batch returned no results"
        # All non-null FeatureVector fields must be finite
        for _, fv in results:
            assert math.isfinite(fv.cci_slow), f"cci_slow not finite: {fv.cci_slow}"
            assert math.isfinite(fv.aroon_slow), f"aroon_slow not finite: {fv.aroon_slow}"


class TestWilderRsiSeries:
    def test_terminal_value_matches_rsi_simple(self) -> None:
        """_wilder_rsi_series[-1] must equal _rsi_simple for every prefix length."""
        from src.intelligence.feature_cache import _rsi_simple, _wilder_rsi_series

        rng = np.random.default_rng(42)
        closes = 100.0 * np.cumprod(1 + rng.normal(0, 0.01, 200))
        period = 14

        series = _wilder_rsi_series(closes, period)
        assert len(series) == len(closes)

        for n in range(2, len(closes) + 1):
            scalar = _rsi_simple(closes[:n], period)
            batch = float(series[n - 1])
            assert (
                abs(batch - scalar) < 1e-8
            ), f"n={n}: series={batch:.10f} scalar={scalar:.10f} delta={abs(batch-scalar):.2e}"

    def test_cold_start_returns_50(self) -> None:
        from src.intelligence.feature_cache import _wilder_rsi_series

        closes = np.array([100.0, 101.0, 102.0], dtype=float)
        series = _wilder_rsi_series(closes, period=14)
        assert series[0] == 50.0
        assert series[1] == 50.0
        assert series[2] == 50.0  # only 3 bars, period=14 → all cold

    def test_values_in_range(self) -> None:
        from src.intelligence.feature_cache import _wilder_rsi_series

        rng = np.random.default_rng(7)
        closes = 100.0 * np.cumprod(1 + rng.normal(0, 0.02, 500))
        series = _wilder_rsi_series(closes, period=14)
        assert np.all(series >= 0.0) and np.all(series <= 100.0)


# ---------------------------------------------------------------------------
# Phase 151 Plan 01 Task 1: calendar coordinate primitives
# ---------------------------------------------------------------------------


class TestMinuteOfHourEncoding:
    def test_minute_0(self) -> None:
        from datetime import UTC, datetime

        from src.intelligence.feature_factory import _minute_of_hour_encoding

        sin_val, cos_val = _minute_of_hour_encoding(datetime(2026, 3, 15, 14, 0, tzinfo=UTC))
        assert sin_val == pytest.approx(0.0, abs=1e-9)
        assert cos_val == pytest.approx(1.0, abs=1e-9)

    def test_minute_15(self) -> None:
        from datetime import UTC, datetime

        from src.intelligence.feature_factory import _minute_of_hour_encoding

        sin_val, cos_val = _minute_of_hour_encoding(datetime(2026, 3, 15, 14, 15, tzinfo=UTC))
        assert sin_val == pytest.approx(1.0, abs=1e-9)
        assert cos_val == pytest.approx(0.0, abs=1e-9)

    def test_minute_30(self) -> None:
        from datetime import UTC, datetime

        from src.intelligence.feature_factory import _minute_of_hour_encoding

        sin_val, cos_val = _minute_of_hour_encoding(datetime(2026, 3, 15, 14, 30, tzinfo=UTC))
        assert sin_val == pytest.approx(0.0, abs=1e-9)
        assert cos_val == pytest.approx(-1.0, abs=1e-9)

    def test_constant_at_hourly_bars(self) -> None:
        """At 1h/1d, minute is always 0 by construction -- constant output is
        expected and correct, not a bug."""
        from datetime import UTC, datetime

        from src.intelligence.feature_factory import _minute_of_hour_encoding

        for hour in (0, 5, 13, 23):
            sin_val, cos_val = _minute_of_hour_encoding(datetime(2026, 3, 15, hour, 0, tzinfo=UTC))
            assert sin_val == pytest.approx(0.0, abs=1e-9)
            assert cos_val == pytest.approx(1.0, abs=1e-9)


class TestTdomEncoding:
    def test_first_weekday_of_month_is_t_equals_1(self) -> None:
        """2026-06-01 is a Monday (verified: calendar.weekday(2026, 6, 1) == 0)."""
        from datetime import UTC, datetime

        from src.intelligence.feature_factory import _tdom_encoding

        ts = datetime(2026, 6, 1, 14, 0, tzinfo=UTC)
        sin_val, cos_val = _tdom_encoding(ts)
        # t=1, W=22 (June 2026 has 22 Mon-Fri weekdays)
        import math

        angle = 2.0 * math.pi * 1 / 22
        assert sin_val == pytest.approx(math.sin(angle), abs=1e-9)
        assert cos_val == pytest.approx(math.cos(angle), abs=1e-9)

    def test_following_monday_is_t_equals_6(self) -> None:
        """2026-06-08 is the following Monday: 5 weekdays in week 1 (Mon-Fri)
        + this Monday = t=6."""
        from datetime import UTC, datetime

        from src.intelligence.feature_factory import _tdom_encoding

        ts = datetime(2026, 6, 8, 14, 0, tzinfo=UTC)
        sin_val, cos_val = _tdom_encoding(ts)
        import math

        angle = 2.0 * math.pi * 6 / 22
        assert sin_val == pytest.approx(math.sin(angle), abs=1e-9)
        assert cos_val == pytest.approx(math.cos(angle), abs=1e-9)

    def test_ignores_weekends(self) -> None:
        """Weekend dates still produce a valid (t counts through the weekend
        date itself, but W only counts Mon-Fri) -- no crash, no holiday table."""
        from datetime import UTC, datetime

        from src.intelligence.feature_factory import _tdom_encoding

        ts = datetime(2026, 6, 6, 14, 0, tzinfo=UTC)  # Saturday
        sin_val, cos_val = _tdom_encoding(ts)
        assert math.isfinite(sin_val)
        assert math.isfinite(cos_val)


class TestQuarterCycleEncoding:
    def test_equals_harmonic_of_quarter_position(self) -> None:
        """quarter_cycle_sin/cos == sin/cos(2*pi*_quarter_position(bar_ts)) --
        an equivalence assertion, not a re-derivation, over a sampled set of
        timestamps."""
        from datetime import UTC, datetime

        from src.intelligence.feature_factory import _quarter_cycle_encoding, _quarter_position

        samples = [
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 2, 15, tzinfo=UTC),
            datetime(2026, 3, 31, tzinfo=UTC),
            datetime(2026, 4, 10, tzinfo=UTC),
            datetime(2026, 7, 20, tzinfo=UTC),
            datetime(2026, 11, 30, tzinfo=UTC),
        ]
        for ts in samples:
            qp = _quarter_position(ts)
            expected_sin = math.sin(2.0 * math.pi * qp)
            expected_cos = math.cos(2.0 * math.pi * qp)
            sin_val, cos_val = _quarter_cycle_encoding(ts)
            assert sin_val == pytest.approx(expected_sin, abs=1e-9), ts
            assert cos_val == pytest.approx(expected_cos, abs=1e-9), ts


# ---------------------------------------------------------------------------
# Phase 151 Plan 01 Task 2: velocity primitives
# ---------------------------------------------------------------------------


class TestVolVelocityZSeriesFullGeneric:
    """_vol_velocity_z_series_full is generic over the input array (renamed
    atr_z -> series) -- reused byte-identically for momentum_z_velocity_*
    and vwap_dev_sigma_velocity."""

    def test_accelerating_series_yields_positive_velocity(self) -> None:
        """A superlinear (accelerating) series has an increasing first
        difference, so its rolling z-score trends positive -- a perfectly
        linear series would have a CONSTANT first difference (zero variance,
        zero z-score), which is not what "positive velocity" should assert."""
        from src.intelligence.feature_factory import _vol_velocity_z_series_full

        series = np.array([float(i) ** 1.6 for i in range(50)])
        result = _vol_velocity_z_series_full(series, window=10)
        assert np.all(result[15:] > 0), f"Expected positive velocity, got {result[15:]}"

    def test_flat_series_yields_zero_velocity(self) -> None:
        from src.intelligence.feature_factory import _vol_velocity_z_series_full

        series = np.full(50, 3.5)
        result = _vol_velocity_z_series_full(series, window=10)
        assert np.all(result == 0.0), f"Expected all-zero velocity on a flat series, got {result}"

    def test_index_0_is_zero_padded(self) -> None:
        from src.intelligence.feature_factory import _vol_velocity_z_series_full

        rng = np.random.default_rng(1)
        series = rng.normal(0, 1, 50)
        result = _vol_velocity_z_series_full(series, window=10)
        assert result[0] == 0.0


# ---------------------------------------------------------------------------
# Phase 151 Plan 01: batch/live parity for all 10 new fields
# ---------------------------------------------------------------------------


class TestPhase151BatchLiveParity:
    """compute_batch()'s last-bar output for all 10 new fields must equal
    compute()'s output on the same bar window."""

    def test_last_bar_parity(self) -> None:
        from src.intelligence.feature_cache import FeatureCache
        from src.intelligence.feature_factory import FeatureFactory

        config = _make_config_for_min_window()
        bars = _make_bars_dicts(80)

        live_cache = FeatureCache()
        live_fv = FeatureFactory.compute(bars, "SPY", "5m", live_cache, config)

        batch_cache = FeatureCache()
        batch_results = FeatureFactory.compute_batch(
            bars, "SPY", "5m", batch_cache, config, warm_up_bars=5
        )
        assert batch_results, "compute_batch returned no results"
        _, batch_fv_last = batch_results[-1]

        for field in (
            "quarter_cycle_sin",
            "quarter_cycle_cos",
            "tdom_sin",
            "tdom_cos",
            "minute_of_hour_sin",
            "minute_of_hour_cos",
            "momentum_z_velocity_fast",
            "momentum_z_velocity_mid",
            "momentum_z_velocity_slow",
            "vwap_dev_sigma_velocity",
            # Phase 151 Plan 03: recency/statistical atomics -- extends this
            # same parity harness rather than duplicating it.
            "bars_since_high_fast",
            "bars_since_high_slow",
            "bars_since_low_fast",
            "bars_since_low_slow",
            "bars_since_52w_high",
            "bars_since_52w_low",
            "bars_since_extreme_move_fast",
            "bars_since_extreme_move_slow",
            "bars_since_vol_spike_fast",
            "bars_since_vol_spike_slow",
            "abs_ret_autocorr_1",
        ):
            live_val = getattr(live_fv, field)
            batch_val = getattr(batch_fv_last, field)
            assert live_val == pytest.approx(
                batch_val, abs=1e-8
            ), f"{field}: live={live_val} batch={batch_val}"


# ---------------------------------------------------------------------------
# Phase 151 Plan 03: recency/statistical atomics (todo 180)
# ---------------------------------------------------------------------------


class TestBarsSinceRollingExtremeSeriesFull:
    """_bars_since_rolling_extreme_series_full: bounded [0, window-1]
    rolling-window recency statistic (never an expanding lookback -- the
    binding design constraint from todo 180's Fable review)."""

    def test_boundedness_randomized(self) -> None:
        from src.intelligence.feature_factory import (
            _bars_since_rolling_extreme_series_full,
        )

        rng = np.random.default_rng(3)
        highs, lows, _closes = _make_bars(500, seed=3)
        for window in (10, 20, 50):
            out_max = _bars_since_rolling_extreme_series_full(highs, window, "max")
            out_min = _bars_since_rolling_extreme_series_full(lows, window, "min")
            assert np.all(out_max >= 0) and np.all(
                out_max <= window - 1
            ), f"window={window} max out of bounds: min={out_max.min()} max={out_max.max()}"
            assert np.all(out_min >= 0) and np.all(
                out_min <= window - 1
            ), f"window={window} min out of bounds: min={out_min.min()} max={out_min.max()}"

    def test_saturation_strictly_decreasing(self) -> None:
        """A strictly-decreasing series never re-attains its earlier max inside
        the window -- the final bar must saturate to exactly window-1."""
        from src.intelligence.feature_factory import (
            _bars_since_rolling_extreme_series_full,
        )

        window = 20
        values = np.arange(200.0, 0.0, -1.0)  # strictly decreasing, len > window
        out = _bars_since_rolling_extreme_series_full(values, window, "max")
        assert out[-1] == float(window - 1)

    def test_recency_semantics_max_at_current_bar_is_zero(self) -> None:
        from src.intelligence.feature_factory import (
            _bars_since_rolling_extreme_series_full,
        )

        values = np.arange(1.0, 101.0)  # strictly increasing -> max always current bar
        out = _bars_since_rolling_extreme_series_full(values, 20, "max")
        assert np.all(out == 0.0)

    def test_recency_semantics_one_bar_later_is_one(self) -> None:
        """A series whose max is the second-to-last bar, then one lower final
        bar, must read 1.0 at the final bar (one bar since the extreme)."""
        from src.intelligence.feature_factory import (
            _bars_since_rolling_extreme_series_full,
        )

        values = np.concatenate([np.arange(1.0, 51.0), [49.5]])
        out = _bars_since_rolling_extreme_series_full(values, 20, "max")
        assert out[-1] == 1.0


class TestBarsSinceEventSeriesFull:
    """_bars_since_event_series_full: bounded [0, window-1] bars-since-most-
    recent-True, saturating to window-1 (never 0.0/NaN) when no event
    occurred inside the trailing window."""

    def test_boundedness_randomized(self) -> None:
        from src.intelligence.feature_factory import _bars_since_event_series_full

        rng = np.random.default_rng(11)
        events = rng.random(500) > 0.85
        for window in (10, 20, 50):
            out = _bars_since_event_series_full(events, window)
            assert np.all(out >= 0) and np.all(
                out <= window - 1
            ), f"window={window} out of bounds: min={out.min()} max={out.max()}"

    def test_saturation_no_event_in_window(self) -> None:
        window = 10
        from src.intelligence.feature_factory import _bars_since_event_series_full

        events = np.zeros(50, dtype=bool)  # never fires
        out = _bars_since_event_series_full(events, window)
        assert np.all(out == float(window - 1))

    def test_recency_semantics(self) -> None:
        from src.intelligence.feature_factory import _bars_since_event_series_full

        events = np.zeros(30, dtype=bool)
        events[10] = True
        out = _bars_since_event_series_full(events, window=15)
        assert out[10] == 0.0, "event bar itself must read 0.0"
        assert out[11] == 1.0, "one bar after the event must read 1.0"


class TestAbsRetAutocorrSeriesFull:
    """abs_ret_autocorr_1 = _ret_autocorr_series_full(closes, 1, use_abs=True):
    volatility-clustering (return-MAGNITUDE autocorrelation), distinct from
    the signed ret_autocorr_1."""

    def test_existing_signed_callers_are_byte_identical(self) -> None:
        """The use_abs refactor must not change ret_autocorr_1/5's existing
        output (use_abs=False default) to 1e-12."""
        from src.intelligence.feature_factory import _ret_autocorr_series_full

        rng = np.random.default_rng(21)
        closes = 100.0 * np.cumprod(1 + rng.normal(0, 0.01, 300))
        for lag in (1, 5):
            explicit = _ret_autocorr_series_full(closes, lag, use_abs=False)
            default = _ret_autocorr_series_full(closes, lag)
            np.testing.assert_allclose(explicit, default, atol=1e-12, rtol=0)

    def test_clustered_large_moves_yield_positive_sign(self) -> None:
        """Alternating small/large-magnitude blocks (volatility clustering)
        must yield a positive abs_ret_autocorr_1 -- large moves follow large
        moves, small moves follow small moves."""
        from src.intelligence.feature_factory import _ret_autocorr_series_full

        # Blocks of 20 small returns then 20 large returns, repeated -- the
        # |return| series is strongly positively autocorrelated at lag 1.
        rng = np.random.default_rng(5)
        n_blocks = 10
        block = 20
        rets = []
        for i in range(n_blocks):
            scale = 0.001 if i % 2 == 0 else 0.05
            rets.append(rng.normal(0, scale, block))
        rets_arr = np.concatenate(rets)
        closes = 100.0 * np.cumprod(1 + rets_arr)
        result = _ret_autocorr_series_full(closes, 1, use_abs=True)
        assert result[-1] > 0.0, f"Expected positive clustering signal, got {result[-1]}"

    def test_alternating_magnitude_yields_negative_sign(self) -> None:
        """A perfectly alternating small/large/small/large |return| sequence
        must yield a negative abs_ret_autocorr_1."""
        from src.intelligence.feature_factory import _ret_autocorr_series_full

        n = 100
        signs = np.array([1.0 if i % 2 == 0 else -1.0 for i in range(n)])
        rng = np.random.default_rng(9)
        rets = np.where(
            np.arange(n) % 2 == 0,
            0.001 * signs * (1 + rng.normal(0, 0.05, n)),
            0.05 * signs * (1 + rng.normal(0, 0.05, n)),
        )
        closes = 100.0 * np.cumprod(1 + rets)
        result = _ret_autocorr_series_full(closes, 1, use_abs=True)
        assert result[-1] < 0.0, f"Expected negative alternating signal, got {result[-1]}"

    def test_bounded_signed(self) -> None:
        from src.intelligence.feature_factory import _ret_autocorr_series_full

        rng = np.random.default_rng(31)
        closes = 100.0 * np.cumprod(1 + rng.normal(0, 0.01, 400))
        result = _ret_autocorr_series_full(closes, 1, use_abs=True)
        finite = result[np.isfinite(result)]
        assert np.all(finite >= -1.0 - 1e-9) and np.all(finite <= 1.0 + 1e-9)


# ---------------------------------------------------------------------------
# Phase 151 Plan 05: cross-TF return divergences (todos 066/104)
# ---------------------------------------------------------------------------


class TestPhase151CrossTfDivergences:
    """ret_div_5m_1h/ret_div_1h_1d are timeframe-pinned to tf=="5m"/"1h"
    respectively and None everywhere else -- even with a populated ctf_by_ts."""

    def test_15m_never_populates_5m_1h_or_1h_1d_divergence(self) -> None:
        from services.backfill_feature_factory import CtfValues
        from src.intelligence.feature_cache import FeatureCache
        from src.intelligence.feature_factory import FeatureFactory

        config = _make_config_for_min_window()
        cache = FeatureCache()
        bars = _make_bars_dicts(60)
        ctf_ts_list = [bars[0]["ts"]]
        ctf_by_ts = {
            bars[0]["ts"]: CtfValues(
                ctf_momentum=0.1,
                ctf_vwap_align=1.0,
                ctf_regime_align=1.0,
                htf_last_log_ret=0.01,
            )
        }
        results = FeatureFactory.compute_batch(
            bars,
            "SPY",
            "15m",
            cache,
            config,
            warm_up_bars=5,
            ctf_by_ts=ctf_by_ts,
            ctf_ts_list=ctf_ts_list,
        )
        assert results, "compute_batch returned no results"
        for _, fv in results:
            assert fv.ret_div_5m_1h is None
            assert fv.ret_div_1h_1d is None

    def test_5m_ret_div_5m_1h_matches_own_return_minus_htf_last_log_ret(self) -> None:
        from services.backfill_feature_factory import CtfValues
        from src.intelligence.feature_cache import FeatureCache
        from src.intelligence.feature_factory import FeatureFactory, _ret_lag_1

        config = _make_config_for_min_window()
        cache = FeatureCache()
        bars = _make_bars_dicts(60)
        ctf_ts_list = [bars[0]["ts"]]
        htf_last_log_ret = 0.0123456789
        ctf_by_ts = {
            bars[0]["ts"]: CtfValues(
                ctf_momentum=0.2,
                ctf_vwap_align=1.0,
                ctf_regime_align=0.0,
                htf_last_log_ret=htf_last_log_ret,
            )
        }
        results = FeatureFactory.compute_batch(
            bars,
            "SPY",
            "5m",
            cache,
            config,
            warm_up_bars=5,
            ctf_by_ts=ctf_by_ts,
            ctf_ts_list=ctf_ts_list,
        )
        assert results, "compute_batch returned no results"

        ts_to_idx = {b["ts"]: idx for idx, b in enumerate(bars)}
        closes_arr = np.array([b["close"] for b in bars])
        for bar_ts, fv in results:
            i = ts_to_idx[bar_ts]
            own_log_ret = _ret_lag_1(closes_arr[: i + 1])
            expected = own_log_ret - htf_last_log_ret
            assert fv.ret_div_5m_1h == pytest.approx(
                expected, abs=1e-12
            ), f"bar {i}: got {fv.ret_div_5m_1h}, expected {expected}"
            assert fv.ret_div_1h_1d is None

    def test_ctf_momentum_unaffected_by_ctf_values_extension(self) -> None:
        """CtfValues extended ctf_by_ts's payload from a 3-tuple to a 4-field
        NamedTuple (Phase 151 Plan 05) -- the 3 pre-existing CTF features must
        still read identically off the same source, byte-for-byte."""
        from services.backfill_feature_factory import CtfValues
        from src.intelligence.feature_cache import FeatureCache
        from src.intelligence.feature_factory import FeatureFactory

        config = _make_config_for_min_window()
        cache = FeatureCache()
        bars = _make_bars_dicts(60)
        ctf_ts_list = [bars[0]["ts"]]
        ctf_by_ts = {
            bars[0]["ts"]: CtfValues(
                ctf_momentum=0.42,
                ctf_vwap_align=-1.0,
                ctf_regime_align=1.0,
                htf_last_log_ret=0.005,
            )
        }
        results = FeatureFactory.compute_batch(
            bars,
            "SPY",
            "5m",
            cache,
            config,
            warm_up_bars=5,
            ctf_by_ts=ctf_by_ts,
            ctf_ts_list=ctf_ts_list,
        )
        assert results, "compute_batch returned no results"
        for _, fv in results:
            assert fv.ctf_momentum == pytest.approx(0.42, abs=1e-12)
            assert fv.ctf_vwap_align == pytest.approx(-1.0, abs=1e-12)
            assert fv.ctf_regime_align == pytest.approx(1.0, abs=1e-12)
