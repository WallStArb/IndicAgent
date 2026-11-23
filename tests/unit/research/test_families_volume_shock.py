"""Family 10 kernels (volume shock): rank, 40-of-50 rule, no_fill, causality, basis invariance."""

import numpy as np
import pytest

from src.intelligence.research.families.volume_shock import (
    residualize_rows,
    rolling_centred_rank,
    trailing_sum,
    volume_rank,
    volume_shock,
)


def _volume(seed=0, sessions=70, names=8):
    rng = np.random.default_rng(seed)
    return np.exp(rng.normal(12.0, 0.6, (sessions, names))).round()


def _ref_rank(x, window):
    out = np.full(x.shape, np.nan)
    for d in range(window - 1, len(x)):
        for i in range(x.shape[1]):
            w = x[d - window + 1 : d + 1, i]
            w = w[np.isfinite(w)]
            if np.isfinite(x[d, i]) and len(w) >= 2:
                avg = (w < x[d, i]).sum() + ((w == x[d, i]).sum() - 1) / 2
                out[d, i] = avg / (len(w) - 1) - 0.5
    return out


def test_rank_matches_the_definition_with_ties_and_gaps():
    x = _volume(sessions=30)
    x[3:6, 1] = np.nan
    x[10, 2] = x[9, 2]  # a tie
    got = rolling_centred_rank(x, window=8, min_finite=2)
    np.testing.assert_allclose(got, _ref_rank(x, 8), equal_nan=True, rtol=1e-12)


def test_rank_range_and_the_window_edge():
    x = np.array([[9.0], [1.0], [1.0], [1.0], [2.0]])
    got = rolling_centred_rank(x, window=4, min_finite=2)[:, 0]
    assert np.isnan(got[:3]).all()
    assert got[3] == pytest.approx(1 / 3 - 0.5)  # window rows 0..3 still holds the 9; 1 ties thrice
    assert got[4] == pytest.approx(1.0 - 0.5)  # 9 has left the window; 2 is the max of 4


def test_a_window_reaching_before_the_panel_is_not_filled():
    got = volume_rank(_volume(sessions=60), window=50, short=1, min_finite=40)
    assert np.isnan(got[:49]).all() and np.isfinite(got[49:]).any()


def test_forty_of_fifty_rule_and_nonpositive_volume_is_missing():
    v = _volume(sessions=60)
    v[10:21, 0] = 0.0  # 11 non-trading sessions: 39 of 50 remain at row 59
    v[10:20, 1] = 0.0  # 10 missing: exactly 40 remain
    got = volume_rank(v, window=50, short=1, min_finite=40)
    assert np.isnan(got[59, 0]) and np.isfinite(got[59, 1])
    assert np.isnan(got[15, 0])  # own session missing


def test_short_mean_needs_all_its_sessions():
    v = _volume(sessions=60)
    v[58, 2] = np.nan
    got = volume_rank(v, window=50, short=5, min_finite=40)
    assert np.isnan(got[58:, 2]).all() and np.isfinite(got[57, 2]) and np.isfinite(got[59, 3])


def test_scale_and_basis_invariance_per_name():
    v = _volume()
    scaled = v.copy()
    scaled[:, 0] *= 0.41  # a constant basis factor on one name
    scaled[:, 1] *= 1000.0
    for short in (1, 5):
        a = volume_rank(v, window=50, short=short, min_finite=40)
        b = volume_rank(scaled, window=50, short=short, min_finite=40)
        np.testing.assert_array_equal(a, b)


def test_causality_future_rows_do_not_move_row_d():
    v, e = _volume(), np.random.default_rng(1).normal(0, 0.02, (70, 8))
    base = volume_shock(v, e, window=50, short=5, min_finite=40, min_names=4)
    v2, e2 = v.copy(), e.copy()
    v2[60:], e2[60:] = v2[60:] * 7, e2[60:] + 0.3
    moved = volume_shock(v2, e2, window=50, short=5, min_finite=40, min_names=4)
    np.testing.assert_array_equal(base[:60], moved[:60])
    assert not np.array_equal(base[60:], moved[60:], equal_nan=True)


def test_residual_is_orthogonal_to_the_design_and_masks_thin_rows():
    rng = np.random.default_rng(2)
    e = rng.normal(0, 0.02, (3, 300))
    y = 0.5 * e - 3.0 * np.abs(e) + rng.normal(0, 0.1, e.shape)
    out = residualize_rows(y, e, min_names=200)
    for r in out:
        assert abs(r.mean()) < 1e-12  # intercept absorbed
    assert abs(out[0] @ e[0]) < 1e-10 and abs(out[0] @ np.abs(e[0])) < 1e-10
    y[1, :150] = np.nan
    assert np.isnan(residualize_rows(y, e, min_names=200)[1]).all()
    assert np.isfinite(residualize_rows(y, e, min_names=100)[1, 150:]).all()


def test_trailing_sum_needs_the_full_span():
    e = np.array([[1.0], [2.0], [np.nan], [4.0], [5.0], [6.0]])
    got = trailing_sum(e, 3)[:, 0]
    assert np.isnan(got[:4]).all()  # two rows short, then the gap sits inside the span
    assert np.isnan(got[4]) and got[5] == 15.0


def test_shape_and_parameter_guards():
    with pytest.raises(ValueError):
        volume_rank(np.ones(5), window=50, short=1, min_finite=40)
    with pytest.raises(ValueError):
        volume_rank(_volume(), window=5, short=5, min_finite=4)
    with pytest.raises(ValueError):
        residualize_rows(np.ones((3, 4)), np.ones((3, 5)), min_names=2)
