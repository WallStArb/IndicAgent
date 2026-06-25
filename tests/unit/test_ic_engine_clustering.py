import numpy as np

from services.ic_engine import _cluster_features


def test_correlated_pairs_cluster_together():
    """Two perfectly-correlated pairs + one independent feature -> 3 clusters."""
    rng = np.random.default_rng(0)
    n = 100
    a = rng.standard_normal(n)
    b = rng.standard_normal(n)
    c = rng.standard_normal(n)
    # pair1: a and a (identical), pair2: b and b, independent: c
    X_nd = np.column_stack([a, a, b, b, c])
    labels = _cluster_features(X_nd, cluster_max_corr=0.70)
    assert labels[0] == labels[1]  # pair1 same cluster
    assert labels[2] == labels[3]  # pair2 same cluster
    assert len(set(labels)) == 3  # 3 distinct clusters


def test_single_feature():
    """Single column -> length-1 label array."""
    X_nd = np.random.default_rng(1).standard_normal((50, 1))
    labels = _cluster_features(X_nd, cluster_max_corr=0.70)
    assert labels.shape == (1,)
    assert len(set(labels)) == 1


def test_all_identical_features():
    """All columns identical -> single cluster."""
    col = np.random.default_rng(2).standard_normal(50)
    X_nd = np.column_stack([col] * 5)
    labels = _cluster_features(X_nd, cluster_max_corr=0.70)
    assert len(set(labels)) == 1
