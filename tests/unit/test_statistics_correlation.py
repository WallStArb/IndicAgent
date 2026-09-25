import numpy as np

from src.intelligence.statistics.correlation import pairwise_corr


def test_complete_data_matches_numpy():
    x = np.random.default_rng(0).normal(size=(200, 5))
    np.testing.assert_allclose(pairwise_corr(x), np.corrcoef(x.T), atol=1e-12)


def test_pairs_use_only_joint_rows():
    rng = np.random.default_rng(1)
    x = rng.normal(size=(300, 3))
    x[:100, 0] = np.nan
    x[200:, 1] = np.nan
    joint = np.isfinite(x[:, 0]) & np.isfinite(x[:, 1])
    a = x[joint, 0] - np.nanmean(x[:, 0])
    b = x[joint, 1] - np.nanmean(x[:, 1])
    expected = (a @ b) / np.sqrt((a @ a) * (b @ b))
    np.testing.assert_allclose(pairwise_corr(x)[0, 1], expected)


def test_thin_overlap_and_constant_columns_give_zero():
    x = np.random.default_rng(2).normal(size=(50, 3))
    x[:, 2] = 1.0
    x[10:, 1] = np.nan  # 10 joint rows with column 0
    c = pairwise_corr(x, min_overlap=20)
    assert c[0, 1] == 0.0 and c[0, 2] == 0.0
    np.testing.assert_array_equal(np.diag(c), 1.0)
