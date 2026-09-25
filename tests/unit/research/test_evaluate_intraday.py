"""The evaluator on an intraday grid: whole-session shifts, row validity, row units."""

import functools

import numpy as np
import pytest

from scripts.analysis.sleeve_walk_forward.config import HarnessConfig
from src.intelligence.research.evaluate import (
    ROW_SCALED_FIELDS,
    UNSCALED_FIELDS,
    EvaluationConfig,
    EvaluatorMisuse,
    evaluate,
    rows_config,
    session_shifts,
    sub_period_masks,
    trade_mask,
)
from src.intelligence.research.portfolio import PortfolioConfig, fixed_sign_returns
from src.intelligence.research.signals import SignalSource

BPS = 4
CFG = HarnessConfig(
    warmup_sessions=20,
    calibration_refit_sessions=10,
    min_shift=10,
    trading_start="2000-01-01",
    sub_periods=(("2000-01-01", "2000-12-31"),),
    bootstrap_reps=50,
)


def _intraday(seed, n_sessions=120, m=6):
    rng = np.random.default_rng(seed)
    n = n_sessions * BPS
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, (n, m)), axis=0))
    fwd = rng.normal(0, 0.003, (n, m))
    alpha = rng.normal(size=(n, m))
    start = np.datetime64("2000-01-03T14:30")
    dates = start + np.arange(n) * np.timedelta64(60, "m")
    return alpha, fwd, closes, dates


def test_session_shifts_are_whole_sessions():
    shifts = session_shifts(40, 4, min_shift=3, memory=5)  # memory rounds up to 2 sessions
    assert (shifts % 4 == 0).all()
    np.testing.assert_array_equal(shifts // 4, np.arange(3, 10 - 3 - 2 + 1))


def test_session_shifts_rejects_a_partial_session():
    with pytest.raises(EvaluatorMisuse, match="whole number"):
        session_shifts(41, 4, min_shift=3, memory=0)


def test_every_config_field_is_classified_for_row_conversion():
    fields = set(EvaluationConfig.__annotations__) | set(PortfolioConfig.__annotations__)
    assert fields == set(ROW_SCALED_FIELDS) | set(UNSCALED_FIELDS)
    assert not set(ROW_SCALED_FIELDS) & set(UNSCALED_FIELDS)


def test_rows_config_scales_session_lengths_only():
    rcfg = rows_config(CFG, BPS)
    assert rcfg.warmup_sessions == 80 and rcfg.calibration_refit_sessions == 40
    assert rcfg.bootstrap_mean_block == CFG.bootstrap_mean_block * BPS
    assert rcfg.min_shift == CFG.min_shift
    assert rows_config(CFG, 1) is CFG


def test_intraday_null_uses_whole_session_shifts():
    alpha, fwd, closes, dates = _intraday(0)
    res = evaluate(
        alpha,
        fwd,
        closes,
        dates,
        CFG,
        mv_condition_max=1000.0,
        ic_shrinkage_k=100.0,
        bars_per_session=BPS,
    )
    assert (res.shifts % BPS == 0).all() and len(res.shifts) > 0


def test_intraday_rejects_bar_level_shifts():
    alpha, fwd, closes, dates = _intraday(0)
    with pytest.raises(EvaluatorMisuse, match="whole sessions"):
        evaluate(
            alpha,
            fwd,
            closes,
            dates,
            CFG,
            mv_condition_max=1000.0,
            ic_shrinkage_k=100.0,
            bars_per_session=BPS,
            shifts=np.array([BPS * 10 + 1]),
        )


def test_invalid_rows_never_enter_the_statistic():
    alpha, fwd, closes, dates = _intraday(1)
    kw = dict(
        mv_condition_max=1000.0,
        ic_shrinkage_k=100.0,
        bars_per_session=BPS,
        construction=functools.partial(fixed_sign_returns, direction=1.0),
        shifts=np.arange(10, 20) * BPS,
    )
    valid = np.ones(len(dates), dtype=bool)
    valid[3::BPS] = False  # every session's last slot is not a bar
    base = evaluate(alpha, fwd, closes, dates, CFG, valid=valid, **kw)
    # Whatever those rows' returns are, the statistic ignores them.
    fwd2 = fwd.copy()
    fwd2[~valid] = 0.5
    moved = evaluate(alpha, fwd2, closes, dates, CFG, valid=valid, **kw)
    np.testing.assert_array_equal(base.sharpe_obs, moved.sharpe_obs)
    np.testing.assert_array_equal(base.sharpe_null, moved.sharpe_null)


def test_signal_source_memory_includes_the_forward_span():
    src = SignalSource(lambda p: p.close, memory=10, direction=-1.0, n_tested=1, horizon=3)
    kw = src.evaluate_kwargs()
    assert kw["memory"] == 14 and kw["embargo"] == 4
    assert kw["construction"].keywords == {"direction": -1.0}


def test_date_bounds_cover_every_bar_on_the_last_day():
    bars = np.array(
        ["2000-12-29T14:30", "2000-12-29T20:00", "2001-01-02T14:30"], dtype="datetime64[m]"
    )
    np.testing.assert_array_equal(trade_mask(bars, CFG), [True, True, False])
    np.testing.assert_array_equal(sub_period_masks(bars, CFG.sub_periods)[0], [True, True, False])


def test_misuse_is_not_a_value_error():
    # safe_evaluate turns ValueError into FIDELITY BROKEN; misuse must crash instead.
    assert not issubclass(EvaluatorMisuse, ValueError)
    alpha, fwd, closes, dates = _intraday(0)
    with pytest.raises(EvaluatorMisuse, match="pool_factory"):
        evaluate(
            alpha,
            fwd,
            closes,
            dates,
            CFG,
            mv_condition_max=1000.0,
            ic_shrinkage_k=100.0,
            bars_per_session=BPS,
            workers=2,
        )
