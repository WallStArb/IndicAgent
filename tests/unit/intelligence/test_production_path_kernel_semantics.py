"""Kernel semantics through the corpus-rerun path (R2 item 5c).

Restores the behavioural coverage that the streaming `FeatureFactory.compute()` tests carried
(SMC detection, degenerate-input missingness, right-censoring, 1d volume-profile absence, the
calendar ranges), now through `production_series.series_columns`. A missing value is NaN on this
path, never None and never a fabricated neutral. Every check reads the last row of the series.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from src.intelligence.features.feature_factory_config import FeatureFactoryConfig
from tests.unit.intelligence.helpers import ATR_GATED_COUNT_COLUMNS
from tests.unit.intelligence.production_series import series_columns
from tests.unit.intelligence.test_swing_fib_trend_structure_primitives import _make_cfg
from tests.unit.test_feature_factory import _make_bars, _make_config

_BASE_TS = datetime(2023, 1, 3, 14, 0, tzinfo=UTC)
# Declared warmup masks every row inside a kernel's effective memory (the longest SMC kernel
# reads 578 bars), so each fixture sits behind a quiet run longer than that.
WARMUP_BARS = 600


@pytest.fixture(scope="module")
def cfg() -> FeatureFactoryConfig:
    return _make_cfg()


def _last(bars, tf: str = "5m", config=None, symbol: str = "SPY") -> dict[str, float]:
    """The last row of every numeric column, as Python floats (NaN when missing)."""
    columns = series_columns(bars, symbol, tf, config if config is not None else _make_cfg())
    return {name: float(col[-1]) for name, col in columns.items()}


def _wilder_atr(bars: list[dict], period: int) -> float:
    """Wilder ATR after the last bar, computed here so the ATR-unit tests do not lean on the kernel."""
    h = np.array([b["high"] for b in bars])
    lo = np.array([b["low"] for b in bars])
    c = np.array([b["close"] for b in bars])
    tr = np.maximum(h[1:] - lo[1:], np.maximum(abs(h[1:] - c[:-1]), abs(lo[1:] - c[:-1])))
    atr = tr[:period].mean()
    for value in tr[period:]:
        atr = (atr * (period - 1) + value) / period
    return float(atr)


def _extend(bars: list[dict], open_: float, high: float, low: float, close: float) -> None:
    bars.append(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": 1e5,
            "ts": bars[-1]["ts"] + timedelta(minutes=1),
        }
    )


def _candle(open_: float, close: float, wick: float = 0.1) -> tuple[float, float, float, float]:
    return open_, max(open_, close) + wick, min(open_, close) - wick, close


def _warmup_bars(n: int = WARMUP_BARS, base_price: float = 100.0) -> list[dict]:
    """n bars of tiny alternating consolidation: ATR warms, no imbalance or impulse forms."""
    price = base_price
    bars = [
        {
            "open": base_price,
            "high": base_price + 0.05,
            "low": base_price - 0.05,
            "close": base_price,
            "volume": 1e5,
            "ts": _BASE_TS,
        }
    ]
    for i in range(n - 1):
        close = price + (0.05 if i % 2 == 0 else -0.04)
        _extend(bars, price, max(price, close) + 0.05, min(price, close) - 0.05, close)
        price = close
    return bars


def _flat_bars(n: int, price: float = 100.0, half_range: float = 0.0) -> list[dict]:
    return [
        {
            "open": price,
            "high": price + half_range,
            "low": price - half_range,
            "close": price,
            "volume": 1000.0,
            "ts": datetime(2026, 1, 2, 9, 30, tzinfo=UTC) + timedelta(minutes=i),
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Fair value gaps
# ---------------------------------------------------------------------------


def _fvg_base_bars() -> tuple[list[dict], float, float]:
    bars = _warmup_bars()
    last_close = bars[-1]["close"]
    _extend(bars, last_close, last_close + 0.5, last_close - 0.5, last_close + 0.1)
    bar1_high = bars[-1]["high"]
    price = bars[-1]["close"]
    _extend(bars, price, price + 3.0, price - 0.1, price + 2.8)
    price = bars[-1]["close"]
    gap_bottom = bar1_high
    gap_top = gap_bottom + 2.0
    _extend(bars, price, gap_top + 0.5, gap_top, gap_top + 0.3)
    return bars, gap_bottom, gap_top


def _fvg_unfilled_bars() -> list[dict]:
    bars, _, _ = _fvg_base_bars()
    price = bars[-1]["close"]
    for _ in range(5):
        close = price + 0.1
        _extend(bars, price, max(price, close) + 0.1, min(price, close) - 0.05, close)
        price = close
    return bars


def _fvg_filled_bars() -> list[dict]:
    bars, gap_bottom, gap_top = _fvg_base_bars()
    price = bars[-1]["close"]
    _extend(bars, price, gap_top + 0.4, gap_bottom - 0.5, gap_top + 0.2)
    price = bars[-1]["close"]
    for i in range(3):
        close = price + (0.05 if i % 2 == 0 else -0.04)
        _extend(bars, price, max(price, close) + 0.1, min(price, close) - 0.1, close)
        price = close
    return bars


def test_pp_fvg_values_are_the_gap_in_atr_units(cfg):
    bars, gap_bottom, gap_top = _fvg_base_bars()
    price = bars[-1]["close"]
    for _ in range(5):
        close = price + 0.1
        _extend(bars, price, max(price, close) + 0.1, min(price, close) - 0.05, close)
        price = close
    atr = _wilder_atr(bars, cfg.adx_period)
    row = _last(bars, config=cfg)
    assert math.isclose(row["fvg_size_atr"], (gap_top - gap_bottom) / atr, rel_tol=1e-4)
    midpoint = (gap_top + gap_bottom) / 2.0
    assert math.isclose(row["fvg_dist_atr"], abs(bars[-1]["close"] - midpoint) / atr, rel_tol=1e-4)
    assert row["fvg_open_count"] == 1.0


def test_pp_fvg_open_count_is_one_unfilled_and_zero_filled(cfg):
    assert _last(_fvg_unfilled_bars(), config=cfg)["fvg_open_count"] == 1.0
    assert _last(_fvg_filled_bars(), config=cfg)["fvg_open_count"] == 0.0


def test_pp_fvg_is_deterministic(cfg):
    bars = _fvg_unfilled_bars()
    first = _last(bars, config=cfg)
    second = _last(bars, config=cfg)
    for name in ("fvg_dist_atr", "fvg_size_atr", "fvg_open_count"):
        assert first[name] == second[name], name


# ---------------------------------------------------------------------------
# Liquidity sweeps and pools
# ---------------------------------------------------------------------------


def _liq_flat_bars(n: int, price: float = 100.0) -> list[dict]:
    bars = [
        {
            "open": price,
            "high": price + 0.1,
            "low": price - 0.1,
            "close": price,
            "volume": 1e5,
            "ts": _BASE_TS,
        }
    ]
    for _ in range(n - 1):
        _extend(bars, price, price + 0.1, price - 0.1, price)
    return bars


def _sweep_bars() -> list[dict]:
    bars = _liq_flat_bars(WARMUP_BARS)
    price = 100.0
    sh_price = price + 2.0
    _extend(bars, price, sh_price, price - 0.1, price + 0.1)
    price = bars[-1]["close"]
    for _ in range(6):
        _extend(bars, price, price + 0.1, price - 0.1, price)
    _extend(bars, price, sh_price + 0.5, price - 0.1, price - 0.1)
    price = bars[-1]["close"]
    for _ in range(3):
        close = price - 0.05
        _extend(bars, price, price + 0.05, close - 0.05, close)
        price = close
    return bars


def _equal_highs_pool_bars() -> list[dict]:
    bars = _liq_flat_bars(WARMUP_BARS)
    price = 100.0
    _extend(bars, price, 102.0, price - 0.1, price + 0.1)
    price = bars[-1]["close"]
    for _ in range(11):
        _extend(bars, price, price + 0.1, price - 0.1, price)
    _extend(bars, price, 102.02, price - 0.1, price + 0.1)
    price = bars[-1]["close"]
    for _ in range(11):
        _extend(bars, price, price + 0.1, price - 0.1, price)
    return bars


def test_pp_sweep_fires_with_bounded_strength_and_velocity(cfg):
    row = _last(_sweep_bars(), config=cfg)
    assert 0.0 <= row["sweep_strength"] <= 1.0
    assert 0.0 <= row["reclaim_velocity"] <= 1.0
    # the sweep bar is followed by exactly three reclaim bars
    assert row["bars_since_last_sweep"] == 3.0
    bars = _sweep_bars()
    price = bars[-1]["close"]
    _extend(bars, price, price + 0.05, price - 0.05, price)
    assert _last(bars, config=cfg)["bars_since_last_sweep"] == 4.0


def test_pp_no_sweep_in_window_is_missing_not_zero(cfg):
    row = _last(_liq_flat_bars(WARMUP_BARS), config=cfg)
    for name in ("bars_since_last_sweep", "sweep_strength", "reclaim_velocity"):
        assert math.isnan(row[name]), name


def test_pp_equal_highs_cluster_produces_a_buy_side_pool(cfg):
    row = _last(_equal_highs_pool_bars(), config=cfg)
    assert math.isfinite(row["bsl_dist_atr"])
    assert row["bsl_touches"] >= 2.0
    assert row["pool_count"] >= 1.0


def test_pp_liquidity_is_deterministic(cfg):
    bars = _sweep_bars()
    first = _last(bars, config=cfg)
    second = _last(bars, config=cfg)
    for name in ("sweep_strength", "reclaim_velocity", "bars_since_last_sweep", "bsl_dist_atr"):
        assert (first[name] == second[name]) or (
            math.isnan(first[name]) and math.isnan(second[name])
        ), name


# ---------------------------------------------------------------------------
# Order blocks and breakers
# ---------------------------------------------------------------------------


def _bullish_ob_bars() -> list[dict]:
    bars = _warmup_bars()
    last_close = bars[-1]["close"]
    _extend(bars, *_candle(last_close + 0.3, last_close - 0.9))
    price = bars[-1]["close"]
    for _ in range(3):
        _extend(bars, *_candle(price, price + 2.0))
        price += 2.0
    for _ in range(5):
        _extend(bars, *_candle(price, price + 0.1))
        price += 0.1
    return bars


def _bearish_ob_bars() -> list[dict]:
    bars = _warmup_bars()
    last_close = bars[-1]["close"]
    _extend(bars, *_candle(last_close - 0.3, last_close + 0.9))
    price = bars[-1]["close"]
    for _ in range(3):
        _extend(bars, *_candle(price, price - 2.0))
        price -= 2.0
    for _ in range(5):
        _extend(bars, *_candle(price, price - 0.1))
        price -= 0.1
    return bars


def _ob_breaker_retest_bars() -> list[dict]:
    bars = _warmup_bars()
    last_close = bars[-1]["close"]
    _extend(bars, *_candle(last_close + 0.3, last_close - 0.9))
    price = bars[-1]["close"]
    for _ in range(3):
        _extend(bars, *_candle(price, price + 2.0))
        price = bars[-1]["close"]
    _extend(bars, *_candle(price, price - 3.5))
    price = bars[-1]["close"]
    _extend(bars, *_candle(price, price - 3.5))
    price = bars[-1]["close"]
    _extend(bars, *_candle(price, price + 3.8))
    return bars


def test_pp_bullish_order_block_fires(cfg):
    row = _last(_bullish_ob_bars(), config=cfg)
    assert math.isfinite(row["ob_bull_dist_atr"]) and row["ob_bull_dist_atr"] != 0.0
    assert 0.0 <= row["ob_strength"] <= 1.0


def test_pp_bearish_order_block_fires(cfg):
    row = _last(_bearish_ob_bars(), config=cfg)
    assert math.isfinite(row["ob_bear_dist_atr"]) and row["ob_bear_dist_atr"] != 0.0
    assert 0.0 <= row["ob_strength"] <= 1.0


def test_pp_breaker_and_mitigation_separate_a_broken_block_from_an_untouched_one(cfg):
    broken = _last(_ob_breaker_retest_bars(), config=cfg)
    untouched = _last(_bullish_ob_bars(), config=cfg)
    assert broken["breaker_block_active"] == 1.0
    assert math.isfinite(broken["breaker_dist_atr"])
    assert 0.0 < broken["ob_mitigation_pct"] <= 1.0
    assert broken["ob_mitigated_flag"] == 1.0
    assert untouched["breaker_block_active"] == 0.0
    assert untouched["ob_mitigation_pct"] == 0.0
    assert untouched["ob_mitigated_flag"] == 0.0


def test_pp_breaker_is_active_when_the_close_sits_inside_the_flipped_zone(cfg):
    """A bullish block mitigated then retested from below flips bearish; a close that ends
    inside the zone (not above it) is active through the in-zone branch alone."""
    bars = _ob_breaker_retest_bars()[:-1]
    price = bars[-1]["close"]
    _extend(bars, *_candle(price, price + 1.5))
    row = _last(bars, config=cfg)
    assert row["breaker_block_active"] == 1.0
    assert row["breaker_dist_atr"] < 0.1  # next to the zone midpoint, not above the zone


# ---------------------------------------------------------------------------
# Break of structure and change of character
# ---------------------------------------------------------------------------


def _ramp(start: float, end: float, n: int) -> list[float]:
    return list(np.linspace(start, end, n + 1))[1:]


def _bars_from_path(closes_path: list[float], wick: float = 0.05) -> list[dict]:
    prior = closes_path[0]
    bars = [
        {
            "open": prior,
            "high": prior + wick,
            "low": prior - wick,
            "close": prior,
            "volume": 1e5,
            "ts": _BASE_TS,
        }
    ]
    for close in closes_path[1:]:
        bars.append(
            {
                "open": prior,
                "high": close + wick,
                "low": close - wick,
                "close": close,
                "volume": 1e5,
                "ts": bars[-1]["ts"] + timedelta(minutes=1),
            }
        )
        prior = close
    return bars


def _uptrend_bos_path() -> list[float]:
    path = [100.0] * WARMUP_BARS
    path += _ramp(100.0, 110.0, 6)
    path += _ramp(110.0, 102.0, 6)
    path += _ramp(102.0, 125.0, 6)
    path += _ramp(125.0, 108.0, 6)
    path += _ramp(108.0, 132.0, 6)
    path += _ramp(132.0, 133.0, 3)
    return path


def _downtrend_choch_path() -> list[float]:
    path = [100.0] * WARMUP_BARS
    path += _ramp(100.0, 125.0, 6)
    path += _ramp(125.0, 108.0, 6)
    path += _ramp(108.0, 110.0, 6)
    path += _ramp(110.0, 95.0, 6)
    path += _ramp(95.0, 130.0, 6)
    path += _ramp(130.0, 131.0, 3)
    return path


def test_pp_bullish_break_in_an_uptrend_is_no_change_of_character(cfg):
    row = _last(_bars_from_path(_uptrend_bos_path()), config=cfg)
    assert row["bos_direction"] == 1.0
    assert math.isfinite(row["bos_strength"]) and row["bos_strength"] > 0.0
    assert row["smc_trend_direction"] == 1.0
    assert row["choch_direction"] == 0.0
    assert row["bars_since_last_shift"] >= 0.0
    assert row["bars_since_last_shift"] == float(int(row["bars_since_last_shift"]))


def test_pp_break_against_a_downtrend_is_a_change_of_character(cfg):
    row = _last(_bars_from_path(_downtrend_choch_path()), config=cfg)
    assert row["smc_trend_direction"] == -1.0
    assert row["bos_direction"] == 1.0
    assert row["choch_direction"] == 1.0
    assert math.isfinite(row["choch_strength"]) and row["choch_strength"] > 0.0
    assert row["choch_strength"] == row["bos_strength"]


# ---------------------------------------------------------------------------
# Supply and demand zones
# ---------------------------------------------------------------------------


def _zone_bars(direction: float) -> list[dict]:
    bars = _warmup_bars()
    price = bars[-1]["close"]
    base_high = price + 0.02
    base_low = price - 0.02
    for _ in range(3):
        close = price + (0.005 if direction > 0 else -0.005)
        high = max(price, close) + 0.015
        low = min(price, close) - 0.015
        base_high = max(base_high, high)
        base_low = min(base_low, low)
        _extend(bars, price, high, low, close)
        price = close
    if direction > 0:
        imp_open = base_high + 0.5
        imp_close = imp_open + 4.0
    else:
        imp_open = base_low - 0.5
        imp_close = imp_open - 4.0
    _extend(
        bars,
        imp_open,
        max(imp_open, imp_close) + 0.05,
        min(imp_open, imp_close) - 0.05,
        imp_close,
    )
    price = imp_close
    for _ in range(5):
        close = price + (0.15 if direction > 0 else -0.15)
        _extend(bars, price, max(price, close) + 0.02, min(price, close) - 0.02, close)
        price = close
    return bars


def test_pp_demand_zone_fires(cfg):
    row = _last(_zone_bars(1.0), config=cfg)
    assert math.isfinite(row["demand_dist_atr"]) and row["demand_dist_atr"] != 0.0
    assert 0.0 <= row["demand_freshness"] <= 1.0
    assert row["active_demand_zones"] >= 1.0
    assert 0.0 <= row["zone_friction_score"] <= 1.0


def test_pp_supply_zone_fires(cfg):
    row = _last(_zone_bars(-1.0), config=cfg)
    assert math.isfinite(row["supply_dist_atr"]) and row["supply_dist_atr"] != 0.0
    assert 0.0 <= row["supply_freshness"] <= 1.0
    assert row["active_supply_zones"] >= 1.0
    assert 0.0 <= row["zone_friction_score"] <= 1.0


# ---------------------------------------------------------------------------
# Degenerate input, right-censoring, no-object series
# ---------------------------------------------------------------------------


def test_pp_bar_close_pos_is_the_midpoint_and_missing_when_high_equals_low():
    bars = _make_bars(50)
    bars[-1].update(high=10.0, low=8.0, close=9.0, open=9.0)
    assert math.isclose(_last(bars, "5m", _make_config())["bar_close_pos"], 0.5, abs_tol=1e-6)

    bars = _make_bars(50)
    bars[-1].update(high=10.0, low=10.0, close=10.0, open=10.0)
    row = _last(bars, "5m", _make_config())
    # a ratio over a range that does not exist is missing, never a fabricated neutral
    for name in ("bar_close_pos", "body_ratio", "upper_wick_ratio", "lower_wick_ratio"):
        assert math.isnan(row[name]), name
    assert math.isnan(row["up_vol_body_diff"])
    assert math.isfinite(row["range_efficiency"])


def test_pp_bars_since_event_columns_are_right_censored_on_a_flat_series():
    row = _last(_flat_bars(WARMUP_BARS + 100), "5m", _make_config())
    for name in (
        "bars_since_extreme_move_fast",
        "bars_since_extreme_move_slow",
        "bars_since_vol_spike_fast",
        "bars_since_vol_spike_slow",
    ):
        assert math.isnan(row[name]), name
    assert row["bars_since_high_fast"] == 0.0
    assert row["bars_since_low_fast"] == 0.0


_NO_OBJECT_COLUMNS = (
    "sr_resist_dist",
    "sr_support_dist",
    "resistance_strength",
    "support_strength",
    "resistance_age_bars",
    "support_age_bars",
    "poc_dist_atr",
    "va_position",
    "price_in_value_area",
    "in_lvn",
    "ob_bull_dist_atr",
    "ob_bear_dist_atr",
    "ob_strength",
    "ob_mitigation_pct",
    "breaker_dist_atr",
    "fvg_dist_atr",
    "fvg_size_atr",
    "sweep_strength",
    "reclaim_velocity",
    "bars_since_last_sweep",
    "bsl_dist_atr",
    "ssl_dist_atr",
    "demand_dist_atr",
    "supply_dist_atr",
    "demand_freshness",
    "supply_freshness",
    "zone_friction_score",
    "bos_strength",
    "choch_strength",
    "bars_since_last_shift",
)
_ZERO_STATE_COLUMNS = (
    "ob_mitigated_flag",
    "breaker_block_active",
    "fvg_open_count",
    "bos_direction",
    "choch_direction",
    "smc_trend_direction",
)


def test_pp_flat_series_has_no_object_columns_and_no_none():
    columns = series_columns(_flat_bars(WARMUP_BARS + 100), "SPY", "5m", _make_config())
    assert all(col.dtype.kind == "f" for col in columns.values()), "no object dtype column"
    row = {name: float(col[-1]) for name, col in columns.items()}
    for name in _NO_OBJECT_COLUMNS:
        assert math.isnan(row[name]), f"{name} must be missing with no object in the window"
    for name in _ZERO_STATE_COLUMNS:
        assert row[name] == 0.0, f"{name} keeps its measured 0.0 on a flat series"
    for name in ATR_GATED_COUNT_COLUMNS:
        assert math.isnan(row[name]), f"{name}: ATR == 0 leaves its detection unmeasurable"
    assert row["bars_since_52w_high"] == 0.0


_VP_AND_POOL_COLUMNS = frozenset(
    {"poc_dist_atr", "va_position", "price_in_value_area", "in_lvn", "bsl_dist_atr", "ssl_dist_atr"}
)


def test_pp_quiet_series_with_a_valid_atr_has_no_smc_or_sr_object(cfg):
    """ATR is positive here, so a NaN is the missing object itself, never the ATR gate: the
    gap, block, sweep, zone and break distances must not read 0.0 or a neutral."""
    bars = _warmup_bars()
    assert _wilder_atr(bars, cfg.adx_period) > 0.0
    row = _last(bars, config=cfg)
    for name in _NO_OBJECT_COLUMNS:
        if name in _VP_AND_POOL_COLUMNS:  # the alternating wiggle does form profile levels
            continue
        assert math.isnan(row[name]), f"{name} must be missing when no object exists"
    for name in _ZERO_STATE_COLUMNS:
        assert row[name] == 0.0, name


# ---------------------------------------------------------------------------
# 1d volume profile, calendar
# ---------------------------------------------------------------------------


def test_pp_1d_volume_profile_session_columns_are_missing():
    bars = _make_bars(WARMUP_BARS + 100)
    intraday = _last(bars, "5m", _make_config())
    daily = _last(bars, "1d", _make_config())
    for name in ("poc_dist_atr", "va_position"):
        assert math.isfinite(intraday[name]), f"{name}: the intraday control must be measured"
        assert math.isnan(daily[name]), name


@pytest.mark.parametrize(
    "hour,minute,expected",
    [(13, 29, 0.0), (13, 30, 1.0), (14, 0, 1.0), (19, 59, 1.0), (20, 0, 0.0), (2, 0, 0.0)],
    ids=["before_open", "first_in_session", "rth_hour", "last_in_session", "first_out", "night"],
)
def test_pp_in_ny_session_follows_the_bar_time(hour, minute, expected):
    bars = _make_bars(WARMUP_BARS + 100)
    bars[-1]["ts"] = datetime(2026, 6, 4, hour, minute, tzinfo=UTC)
    assert _last(bars, "5m", _make_config())["in_ny_session"] == expected


def test_pp_calendar_columns_stay_in_range_over_a_week():
    base = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
    bars = _make_bars(WARMUP_BARS + 100)
    for i, bar in enumerate(bars):
        bar["ts"] = base + timedelta(hours=3 * i)
    columns = series_columns(bars, "SPY", "5m", _make_config())
    for name in ("dow_sin", "dow_cos"):
        values = columns[name][np.isfinite(columns[name])]
        assert values.size and np.all(values >= -1.0) and np.all(values <= 1.0), name
    month = columns["month_position"]
    month = month[np.isfinite(month)]
    assert month.size and np.all(month > 0.0) and np.all(month <= 1.0)


def test_pp_bounded_volume_columns_stay_in_range():
    columns = series_columns(_make_bars(WARMUP_BARS + 100), "SPY", "5m", _make_config())
    cmf = columns["cmf"][np.isfinite(columns["cmf"])]
    assert cmf.size and np.all(cmf >= -1.0) and np.all(cmf <= 1.0)
    vol_ratio = columns["vol_ratio"][np.isfinite(columns["vol_ratio"])]
    assert vol_ratio.size and np.all(vol_ratio >= 0.0)


def test_pp_efficiency_ratio_and_price_percentile_have_measured_values():
    n = WARMUP_BARS + 100
    base = datetime(2026, 1, 2, 9, 30, tzinfo=UTC)
    rising = [
        {
            "open": 100.0 + i * 0.1,
            "high": 100.0 + i * 0.1 + 0.05,
            "low": 100.0 + i * 0.1 - 0.05,
            "close": 100.0 + i * 0.1,
            "volume": 1000.0,
            "ts": base + timedelta(minutes=i),
        }
        for i in range(n)
    ]
    columns = series_columns(rising, "SPY", "5m", _make_config())
    # perfectly linear movement is fully efficient and the close tops its trailing window
    assert math.isclose(float(columns["efficiency_ratio_fast"][-1]), 1.0, abs_tol=1e-6)
    assert math.isclose(float(columns["price_percentile_fast"][-1]), 1.0, abs_tol=1e-6)
    row = _last(_make_bars(n), "5m", _make_config())
    assert 0.0 < row["efficiency_ratio_fast"] < 1.0
    assert 0.0 < row["price_percentile_fast"] <= 1.0
