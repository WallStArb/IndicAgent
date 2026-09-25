import numpy as np

from scripts.analysis.sleeve_walk_forward.config import HarnessConfig
from scripts.analysis.sleeve_walk_forward.synthetic import run_v2, synthetic_panel

SMALL = dict(n=800, m=6)
CFG = HarnessConfig(
    warmup_sessions=120,
    calibration_refit_sessions=60,
    trading_start="2011-09-01",
    sub_periods=(
        ("2011-09-01", "2012-06-30"),
        ("2012-07-01", "2013-06-30"),
        ("2013-07-01", "2014-12-31"),
    ),
    bootstrap_reps=100,
)


def test_shapes_and_execution_convention():
    alpha, fwd, closes, dates = synthetic_panel(0, signal_ic=0.0, **SMALL)
    assert alpha.shape == fwd.shape == closes.shape == (800, 6)
    assert len(dates) == 800 and dates.dtype == np.dtype("datetime64[D]")
    # fwd_ret[d] = ln(close[d+2] / close[d+1]): entry after d's close, exit one session later.
    np.testing.assert_allclose(fwd[:-2], np.log(closes[2:] / closes[1:-1]), atol=1e-12)
    assert np.isnan(fwd[-2:]).all()


def test_same_seed_same_panel():
    a = synthetic_panel(5, signal_ic=0.1, **SMALL)
    b = synthetic_panel(5, signal_ic=0.1, **SMALL)
    for x, y in zip(a, b):
        np.testing.assert_array_equal(x, y)


def test_no_signal_smoke_pass_rate_is_low():
    out = run_v2(range(10), n_shifts=49, workers=2, cfg=CFG, **SMALL)
    assert out["n_degenerate"] == 0
    assert out["pass_rate"] <= 0.5


def test_planted_signal_smoke_pass_rate_is_high():
    out = run_v2(range(10), n_shifts=49, workers=2, cfg=CFG, signal_ic=0.3, **SMALL)
    assert out["pass_rate"] >= 0.8


def test_signal_panel_computes_the_signal_from_its_own_prices():
    from scripts.analysis.sleeve_walk_forward.signals import tsmom

    alpha, fwd, closes, _ = synthetic_panel(1, signal_ic=0.1, alpha_kind="tsmom", **SMALL)
    assert alpha.shape == fwd.shape == closes.shape == (800, 6)
    assert np.isfinite(alpha).all()  # the dropped history gives a full lookback from row 0
    np.testing.assert_allclose(alpha[252:], tsmom(closes)[252:], atol=1e-12)
    np.testing.assert_allclose(fwd[:-2], np.log(closes[2:] / closes[1:-1]), atol=1e-12)


def test_signal_panel_smoke_null_low_planted_high():
    kw = dict(alpha_kind="tsmom", **SMALL)
    null = run_v2(range(10), n_shifts=49, workers=2, cfg=CFG, **kw)
    assert null["n_degenerate"] == 0 and null["pass_rate"] <= 0.5
    planted = run_v2(range(10), n_shifts=49, workers=2, cfg=CFG, signal_ic=0.3, **kw)
    assert planted["pass_rate"] >= 0.8
