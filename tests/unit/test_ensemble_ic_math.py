"""Unit tests: EnsembleICEngine IC math parity vs ic_engine on synthetic alpha_score.

alpha_score is a single composite predictor (shape [n_obs, 1]). These tests prove
the composed call path (rankdata -> _vectorized_ic -> _p_values_from_ic -> _fisher_z_ci,
all imported from src.intelligence.statistics.ic_math) reproduces the same values as a
direct scipy.stats.spearmanr computation, and that the Fisher-z CI behaves correctly
under signal and null fixtures.

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

from src.intelligence.statistics.ic_math import (
    _circular_shift_null,
    _fisher_z_ci,
    _p_values_from_ic,
    _vectorized_ic,
    apply_bh_fdr,
    fisher_z_difference_p,
)


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


# ---------------------------------------------------------------------------
# fisher_z_difference_p (todo 069 / measurement-ic-engine.md OQ7)
# ---------------------------------------------------------------------------


def test_fisher_z_difference_p_identical_ics_is_one():
    """Two identical IC estimates -> z_diff = 0 -> p = 1.0 (no evidence of a difference)."""
    p = fisher_z_difference_p(ic_a=0.05, n_a=1000, ic_b=0.05, n_b=1000)
    assert abs(p - 1.0) < 1e-9


def test_fisher_z_difference_p_large_gap_large_n_is_significant():
    """A large IC gap (0.10 vs 0.01) with large n on both sides should be detected as a
    significant difference (small p)."""
    p = fisher_z_difference_p(ic_a=0.10, n_a=20000, ic_b=0.01, n_b=20000)
    assert p < 0.01, f"Expected a strongly significant difference, got p={p}"


def test_fisher_z_difference_p_small_gap_small_n_is_not_significant():
    """A small IC gap with modest n should not be distinguishable from noise (large p)."""
    p = fisher_z_difference_p(ic_a=0.021, n_a=200, ic_b=0.019, n_b=200)
    assert p > 0.5, f"Expected a non-significant difference, got p={p}"


def test_fisher_z_difference_p_is_symmetric():
    """The test is symmetric in its two inputs: swapping (a, b) must not change the
    p-value, since it's a two-sided test of |z_diff|."""
    p_ab = fisher_z_difference_p(ic_a=0.08, n_a=5000, ic_b=0.02, n_b=3000)
    p_ba = fisher_z_difference_p(ic_a=0.02, n_a=3000, ic_b=0.08, n_b=5000)
    assert abs(p_ab - p_ba) < 1e-12


def test_fisher_z_difference_p_degenerate_n_returns_nan():
    """n <= 3 on either side makes the SE term undefined (arctanh variance approximation
    requires n > 3) -- must return NaN, not raise or silently return a wrong number."""
    assert np.isnan(fisher_z_difference_p(ic_a=0.05, n_a=3, ic_b=0.05, n_b=1000))
    assert np.isnan(fisher_z_difference_p(ic_a=0.05, n_a=1000, ic_b=0.05, n_b=2))
    assert np.isnan(fisher_z_difference_p(ic_a=0.05, n_a=0, ic_b=0.05, n_b=1000))


def test_fisher_z_difference_p_in_unit_interval():
    """Output must always lie in [0, 1] regardless of IC magnitude or n."""
    rng = np.random.default_rng(11)
    for _ in range(50):
        ic_a = rng.uniform(-0.3, 0.3)
        ic_b = rng.uniform(-0.3, 0.3)
        n_a = rng.integers(10, 50000)
        n_b = rng.integers(10, 50000)
        p = fisher_z_difference_p(ic_a, float(n_a), ic_b, float(n_b))
        assert 0.0 <= p <= 1.0, f"p out of [0,1]: ic_a={ic_a}, ic_b={ic_b}, p={p}"


# ---------------------------------------------------------------------------
# apply_bh_fdr (todo 069: shared BH-FDR wrapper, extracted from three independently
# hand-rolled call sites -- services/ic_engine.py, services/ensemble_ic_engine.py,
# scripts/ops/corpus/ops_oos_holdout_eval.py)
# ---------------------------------------------------------------------------


def test_apply_bh_fdr_empty_input_returns_empty_arrays():
    """No p-values -> no family to correct -> two empty arrays, not an error."""
    reject, p_corrected = apply_bh_fdr([], alpha=0.05)
    assert len(reject) == 0
    assert len(p_corrected) == 0


def test_apply_bh_fdr_preserves_input_order():
    """reject/p_corrected must be parallel arrays in the same order as the input
    p_values list, since callers scatter results back by positional index."""
    p_values = [0.001, 0.5, 0.02, 0.9]
    reject, p_corrected = apply_bh_fdr(p_values, alpha=0.05)
    assert len(reject) == len(p_values)
    assert len(p_corrected) == len(p_values)
    # The strongest raw p-value must still have the smallest corrected p-value.
    assert p_corrected[0] == min(p_corrected)


def test_apply_bh_fdr_vetoes_lone_marginal_p_among_null_strata():
    """A single marginally-significant p-value (p=0.04) surrounded by many null
    strata (p~0.5-0.9) should not survive correction across the full family -- the
    concrete "fluke WIN in one stratum out of ~36" scenario todo 069 exists to catch."""
    p_values = [0.04] + [0.5, 0.6, 0.7, 0.8, 0.9, 0.55, 0.65, 0.75, 0.85] * 4  # 41 values
    reject, _ = apply_bh_fdr(p_values, alpha=0.05)
    assert bool(reject[0]) is False


def test_apply_bh_fdr_passes_multi_stratum_significance():
    """Several strongly significant p-values among many nulls should survive
    correction -- the fix must not veto a genuine, broad-based improvement."""
    p_values = [0.0001, 0.0003, 0.0002, 0.0005] + [0.5, 0.6, 0.7, 0.8, 0.9] * 6  # 34 values
    reject, _ = apply_bh_fdr(p_values, alpha=0.05)
    assert all(bool(r) for r in reject[:4])


# ---------------------------------------------------------------------------
# _circular_shift_null (todo 071 / L4-2 null calibration)
# ---------------------------------------------------------------------------


def test_circular_shift_null_preserves_value_multiset():
    """Shifting must not fabricate or drop any value -- same multiset, same length."""
    rng = np.random.default_rng(7)
    Y = np.array([10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0])
    shifted = _circular_shift_null(Y, rng)
    assert len(shifted) == len(Y)
    assert sorted(shifted.tolist()) == sorted(Y.tolist())


def test_circular_shift_null_never_returns_identity_for_distinct_values():
    """Offset excludes 0 -- with all-distinct values, output must differ from input."""
    Y = np.arange(50.0)
    for seed in range(20):
        rng = np.random.default_rng(seed)
        shifted = _circular_shift_null(Y, rng)
        assert not np.array_equal(shifted, Y)


def test_circular_shift_null_is_deterministic_given_seeded_generator():
    """Two independently-seeded generators with the same seed must produce the same shift."""
    Y = np.arange(30.0)
    rng_a = np.random.default_rng(123)
    rng_b = np.random.default_rng(123)
    shifted_a = _circular_shift_null(Y, rng_a)
    shifted_b = _circular_shift_null(Y, rng_b)
    assert np.array_equal(shifted_a, shifted_b)


def test_circular_shift_null_wraps_circularly_matches_np_roll():
    """Implementation must be np.roll (circular, no truncation) -- verify against a known offset."""
    Y = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    rng = np.random.default_rng(99)
    offset = int(rng.integers(1, len(Y)))
    rng_replay = np.random.default_rng(99)
    shifted = _circular_shift_null(Y, rng_replay)
    assert np.array_equal(shifted, np.roll(Y, offset))


def test_circular_shift_null_handles_length_one():
    """n < 2: no valid nonzero offset exists -- return the array unchanged."""
    rng = np.random.default_rng(1)
    Y = np.array([42.0])
    shifted = _circular_shift_null(Y, rng)
    assert np.array_equal(shifted, Y)
