import numpy as np

from scripts.analysis.sleeve_walk_forward.signals import tsmom


def test_tsmom_is_the_trailing_log_return():
    closes = np.exp(np.arange(10.0))[:, None] * np.array([[1.0, 2.0]])
    alpha = tsmom(closes, lookback=3)
    assert np.isnan(alpha[:3]).all()
    np.testing.assert_allclose(alpha[3:], 3.0)


def test_tsmom_missing_or_bad_close_gives_no_position():
    closes = np.full((10, 1), 100.0)
    closes[5, 0] = np.nan
    closes[2, 0] = 0.0
    alpha = tsmom(closes, lookback=4)
    assert np.isnan(alpha[[5, 9], 0]).all()  # missing close today, then at the lookback start
    assert np.isnan(alpha[6, 0])  # non-positive close at the lookback start
    np.testing.assert_array_equal(alpha[[4, 7, 8], 0], 0.0)


def test_tsmom_is_causal():
    rng = np.random.default_rng(0)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (400, 3)), axis=0))
    changed = closes.copy()
    changed[300:] *= 1.5
    np.testing.assert_array_equal(tsmom(closes)[:300], tsmom(changed)[:300])
