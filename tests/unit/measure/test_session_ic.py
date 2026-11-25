"""Per-session rank IC: exact against scipy per session, with holes, ties and constants."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.stats import spearmanr

from src.intelligence.measure.session_ic import session_rank_ic


def _panel(seed: int = 7, n: int = 12, m: int = 40, k: int = 5):
    rng = np.random.default_rng(seed)
    features = rng.standard_normal((n, m, k))
    target = 0.3 * features[:, :, 0] + rng.standard_normal((n, m))
    exists = rng.random((n, m)) > 0.1
    # holes in two features and in the target, ties in one feature
    features[rng.random((n, m)) > 0.85, 1] = np.nan
    features[rng.random((n, m)) > 0.9, 3] = np.nan
    target[rng.random((n, m)) > 0.95] = np.nan
    features[:, :, 2] = np.round(features[:, :, 2])
    return features, target, exists


def test_matches_scipy_per_session_and_feature():
    features, target, exists = _panel()
    got = session_rank_ic(features, target, exists, min_names=5)
    for i in range(features.shape[0]):
        for f in range(features.shape[2]):
            ok = exists[i] & np.isfinite(target[i]) & np.isfinite(features[i, :, f])
            if ok.sum() < 5:
                assert np.isnan(got[i, f])
                continue
            want = spearmanr(features[i, ok, f], target[i, ok]).statistic
            assert got[i, f] == pytest.approx(want, abs=1e-12)


def test_name_order_does_not_matter():
    features, target, exists = _panel()
    order = np.random.default_rng(3).permutation(features.shape[1])
    a = session_rank_ic(features, target, exists, min_names=5)
    b = session_rank_ic(features[:, order], target[:, order], exists[:, order], min_names=5)
    np.testing.assert_allclose(a, b, atol=1e-12, equal_nan=True)


def test_nan_below_min_names_and_for_constant_columns():
    features, target, exists = _panel(m=12)
    got = session_rank_ic(features, target, exists, min_names=100)
    assert np.isnan(got).all()
    features[:, :, 0] = 1.0
    got = session_rank_ic(features, target, np.ones_like(exists), min_names=5)
    assert np.isnan(got[:, 0]).all()
    assert np.isfinite(got[:, 4]).any()


def test_slot_that_does_not_exist_is_not_an_observation():
    features, target, exists = _panel()
    changed = features.copy()
    changed[~exists] = 1e6  # moving values on non-existing slots changes nothing
    a = session_rank_ic(features, target, exists, min_names=5)
    b = session_rank_ic(changed, target, exists, min_names=5)
    np.testing.assert_array_equal(a, b)


def test_shape_and_min_names_refused():
    features, target, exists = _panel()
    with pytest.raises(ValueError):
        session_rank_ic(features, target[:, :-1], exists, min_names=5)
    with pytest.raises(ValueError):
        session_rank_ic(features, target, exists, min_names=2)


def test_features_sharing_a_hole_pattern_match_scipy():
    features, target, exists = _panel()
    features[:, :, 4] = features[:, :, 1] * 2 + 0.1  # same finite names as feature 1
    got = session_rank_ic(features, target, exists, min_names=5)
    for f in (1, 4):
        for i in range(features.shape[0]):
            ok = exists[i] & np.isfinite(target[i]) & np.isfinite(features[i, :, f])
            if ok.sum() >= 5:
                want = spearmanr(features[i, ok, f], target[i, ok]).statistic
                assert got[i, f] == pytest.approx(want, abs=1e-12)
    np.testing.assert_allclose(got[:, 1], got[:, 4], atol=1e-12, equal_nan=True)
