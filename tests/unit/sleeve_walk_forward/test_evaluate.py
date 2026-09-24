import numpy as np
import pytest

from scripts.analysis.sleeve_walk_forward.config import HarnessConfig
from scripts.analysis.sleeve_walk_forward.evaluate import annualized_sharpe, evaluate

CFG = HarnessConfig(
    warmup_sessions=60,
    calibration_refit_sessions=30,
    min_shift=20,
    trading_start="2000-06-01",
    sub_periods=(
        ("2000-06-01", "2000-08-31"),
        ("2000-09-01", "2000-10-31"),
        ("2000-11-01", "2001-12-31"),
    ),
    bootstrap_reps=200,
)


def _inputs(seed, signal=0.0, n=300, m=5):
    rng = np.random.default_rng(seed)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (n, m)), axis=0))
    fwd = rng.normal(0, 0.01, (n, m))
    alpha = signal * fwd / 0.01 + rng.normal(size=(n, m))
    dates = np.arange(np.datetime64("2000-01-03"), np.datetime64("2000-01-03") + n)
    return alpha, fwd, closes, dates


def test_sharpe_hand_computed():
    r = np.array([0.01, -0.01, 0.02, 0.0])
    want = r.mean() / r.std(ddof=1) * np.sqrt(252)
    assert annualized_sharpe(r, np.ones(4, bool)) == pytest.approx(want)


def test_sharpe_zero_variance_raises():
    with pytest.raises(ValueError):
        annualized_sharpe(np.zeros(5), np.ones(5, bool))


def test_real_run_uses_every_admissible_shift():
    alpha, fwd, closes, dates = _inputs(0)
    res = evaluate(alpha, fwd, closes, dates, CFG, mv_condition_max=1000.0, ic_shrinkage_k=100.0)
    assert res.shifts.tolist() == list(range(20, 300 - 20 + 1))
    assert res.sharpe_null.shape == (len(res.shifts), 3)


def test_deterministic():
    args = _inputs(1)
    a = evaluate(
        *args, CFG, mv_condition_max=1000.0, ic_shrinkage_k=100.0, shifts=np.arange(20, 60)
    )
    b = evaluate(
        *args, CFG, mv_condition_max=1000.0, ic_shrinkage_k=100.0, shifts=np.arange(20, 60)
    )
    np.testing.assert_array_equal(a.sharpe_null, b.sharpe_null)
    np.testing.assert_array_equal(a.excess_ci, b.excess_ci)


def test_parallel_equals_serial():
    args = _inputs(2)
    a = evaluate(
        *args, CFG, mv_condition_max=1000.0, ic_shrinkage_k=100.0, shifts=np.arange(20, 80)
    )
    b = evaluate(
        *args,
        CFG,
        mv_condition_max=1000.0,
        ic_shrinkage_k=100.0,
        shifts=np.arange(20, 80),
        workers=3,
    )
    np.testing.assert_array_equal(a.sharpe_null, b.sharpe_null)


def test_strong_signal_gets_small_p_and_positive_excess():
    res = evaluate(*_inputs(3, signal=0.5), CFG, mv_condition_max=1000.0, ic_shrinkage_k=100.0)
    assert (res.adjusted_p < 0.05).all()
    assert (res.excess > 0).all()


def test_shape_diagnostics_hand_computed():
    from scripts.analysis.sleeve_walk_forward.evaluate import shape_diagnostics

    r = np.array([0.02, -0.01, 0.03, -0.04, 0.01])
    d = shape_diagnostics(r)
    downside = np.sqrt(np.mean(np.minimum(r, 0.0) ** 2))
    assert d["sortino"] == pytest.approx(r.mean() / downside * np.sqrt(252))
    # Log-wealth path 0.02, 0.01, 0.04, 0.00, 0.01: worst peak-to-trough is 0.04 -> 0.00.
    assert d["max_drawdown"] == pytest.approx(0.04)
    assert d["hit_rate"] == pytest.approx(3 / 5)
    assert set(d) == {"sortino", "max_drawdown", "skew", "excess_kurtosis", "hit_rate"}


def test_shape_diagnostics_ignores_nan_and_has_no_downside():
    from scripts.analysis.sleeve_walk_forward.evaluate import shape_diagnostics

    d = shape_diagnostics(np.array([0.01, np.nan, 0.02]))
    assert d["hit_rate"] == 1.0 and d["max_drawdown"] == 0.0 and np.isnan(d["sortino"])


def test_evaluate_reports_diagnostics_for_real_and_null_median():
    res = evaluate(
        *_inputs(4), CFG, mv_condition_max=1000.0, ic_shrinkage_k=100.0, shifts=np.arange(20, 40)
    )
    for arm in res.arms:
        assert set(res.diagnostics[arm]) == {"observed", "null_median"}
        assert "sortino" in res.diagnostics[arm]["observed"]


def test_trade_mask_is_bounded_by_the_last_sub_period():
    from scripts.analysis.sleeve_walk_forward.evaluate import trade_mask

    dates = np.array(
        ["2000-05-31", "2000-06-01", "2001-12-31", "2002-01-02"], dtype="datetime64[D]"
    )
    assert trade_mask(dates, CFG).tolist() == [False, True, True, False]
