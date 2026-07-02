"""Unit tests: EnsembleICEngine IC math parity vs ic_engine on synthetic alpha_score.

alpha_score is a single composite predictor (shape [n_obs, 1]). These tests prove
the composed call path (rankdata -> _vectorized_ic -> _p_values_from_ic -> _fisher_z_ci,
all imported from services.ic_engine) reproduces the same values as a direct
scipy.stats.spearmanr computation, and that the Fisher-z CI behaves correctly under
signal and null fixtures.

No DB, no Kafka. Pure numpy / scipy.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy.stats import rankdata, spearmanr

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ic_engine import _fisher_z_ci, _p_values_from_ic, _vectorized_ic


def _composed_ic(alpha_score: np.ndarray, returns: np.ndarray) -> tuple[float, float, float]:
    """Mirror the EnsembleICEngine worker's per-cell IC computation path.

    alpha_score is ONE predictor -> ranks_X has shape [n_obs, 1].
    """
    ranks_x = rankdata(alpha_score.reshape(-1, 1), axis=0)
    ranks_y = rankdata(returns)
    ic_vector = _vectorized_ic(ranks_x, ranks_y)
    n = len(returns)
    p_value = float(_p_values_from_ic(ic_vector, n)[0])
    ci_lower, ci_upper = _fisher_z_ci(ic_vector, n)
    return float(ic_vector[0]), p_value, float(ci_lower[0])


def test_alpha_score_single_predictor_ic_matches_scipy_spearmanr():
    """IC(alpha_score[1col], returns) via the composed path == scipy.stats.spearmanr."""
    rng = np.random.default_rng(42)
    n = 500
    alpha_score = rng.normal(size=n)
    # Construct returns correlated with alpha_score so IC is nonzero and comparable.
    returns = 0.3 * alpha_score + rng.normal(size=n)

    ic_value, _, _ = _composed_ic(alpha_score, returns)
    expected_ic, _ = spearmanr(alpha_score, returns)

    assert (
        abs(ic_value - expected_ic) < 1e-9
    ), f"Composed IC {ic_value} does not match scipy.stats.spearmanr {expected_ic}"


def test_fisher_ci_lower_positive_when_alpha_score_predicts_returns():
    """A truly predictive alpha_score (strong correlation, large n) yields ci_lower > 0."""
    rng = np.random.default_rng(7)
    n = 5000
    alpha_score = rng.normal(size=n)
    returns = 0.5 * alpha_score + rng.normal(size=n) * 0.5

    ic_value, p_value, ci_lower = _composed_ic(alpha_score, returns)

    assert ic_value > 0.2, f"Expected strong positive IC, got {ic_value}"
    assert ci_lower > 0, f"Expected ci_lower > 0 for genuine signal, got {ci_lower}"
    assert 0.0 <= p_value <= 1.0


def test_fisher_ci_crosses_zero_under_null_fixture():
    """No-signal fixture (independent alpha_score and returns) crosses zero in the CI."""
    rng = np.random.default_rng(99)
    n = 500
    alpha_score = rng.normal(size=n)
    returns = rng.normal(size=n)  # independent of alpha_score

    ic_value, p_value, ci_lower = _composed_ic(alpha_score, returns)

    ranks_x = rankdata(alpha_score.reshape(-1, 1), axis=0)
    ranks_y = rankdata(returns)
    ic_vector = _vectorized_ic(ranks_x, ranks_y)
    _, ci_upper = _fisher_z_ci(ic_vector, n)

    assert (
        ci_lower < 0 < float(ci_upper[0])
    ), f"Expected null CI to straddle zero, got lower={ci_lower}, upper={ci_upper[0]}"


def test_p_values_from_ic_in_unit_interval():
    """_p_values_from_ic output must always lie in [0, 1] regardless of IC magnitude."""
    rng = np.random.default_rng(3)
    for ic_val in [-0.99, -0.5, -0.01, 0.0, 0.01, 0.5, 0.99]:
        ic_vector = np.array([ic_val])
        p = _p_values_from_ic(ic_vector, n=1000)
        assert 0.0 <= float(p[0]) <= 1.0, f"p-value out of [0,1] for ic={ic_val}: {p[0]}"
