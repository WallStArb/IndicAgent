"""Unit tests: sign-consistent walk-forward fold-pass criterion (Component E, todo 094).

`_sign_consistent_wf_pass_count` is the shared pure helper used by BOTH array-shaped
walk-forward blocks in services/ic_engine.py:
  - `_compute_symbol_tf` (per-symbol; output symbol=<SYM>, diagnostic only)
  - `_compute_cross_sectional_tf` (output symbol='POOLED' -- the ONLY block whose
    output `_ELIGIBILITY_BASE_WHERE` reads for ensemble eligibility; load-bearing
    per 143.1-04-PLAN.md Pitfall 1)

Root-cause coverage gap this file closes: `tests/unit/test_ensemble_ic_wf_stability.py`
(despite its name) tests `services/ensemble_ic_engine.py`'s `compute_walk_forward_stable`
-- an unrelated EIC-03 fold-IC-magnitude-ratio proxy, not ic_engine.py's fold-pass
criterion at all. It exercises neither the per-symbol nor the cross-sectional block.
This file is the actual Wave-0-gap-closure target for ic_engine.py's walk-forward fix.

No DB, no Kafka. Pure numpy.
"""

from __future__ import annotations

import numpy as np

from services.ic_engine import _sign_consistent_wf_pass_count


def test_negative_sign_feature_with_consistently_negative_folds_passes():
    """Cross-sectional (POOLED) scenario: a feature with negative full-sample IC whose
    every fold IC is also negative should PASS all folds under the sign-consistent
    criterion -- the exact case the old `(fold_ic_arr > 0)` criterion could never satisfy
    for a contrarian feature, regardless of fold stability."""
    # 3 folds, 1 feature: full-sample IC is negative, every fold IC is negative too.
    ic_vector_nd = np.array([-0.15])
    fold_ic_arr = np.array([[-0.10], [-0.20], [-0.12]])  # [n_folds=3, n_nd=1]

    wf_pass_count_nd = _sign_consistent_wf_pass_count(fold_ic_arr, ic_vector_nd)

    assert wf_pass_count_nd.tolist() == [3], (
        "A persistently-negative feature must pass all 3 folds under the sign-"
        f"consistent criterion; got {wf_pass_count_nd.tolist()}"
    )


def test_folds_that_flip_sign_relative_to_full_sample_fail():
    """A feature whose full-sample sign is negative but whose folds flip sign should
    only count the folds that share the full-sample sign, not all of them."""
    ic_vector_nd = np.array([-0.10])
    # fold 1: negative (matches, passes); fold 2: positive (flips, fails);
    # fold 3: negative (matches, passes).
    fold_ic_arr = np.array([[-0.05], [0.08], [-0.03]])

    wf_pass_count_nd = _sign_consistent_wf_pass_count(fold_ic_arr, ic_vector_nd)

    assert wf_pass_count_nd.tolist() == [
        2
    ], f"Expected 2/3 folds to pass (sign-matching only); got {wf_pass_count_nd.tolist()}"


def test_positive_sign_feature_equivalence_with_old_criterion():
    """Equivalence property: for a positive-full-sample-sign feature, wf_pass_count is
    byte-identical to the old `(fold_ic_arr > 0).sum(axis=0)` criterion -- multiplying
    by the full-sample sign (+1) is a no-op. This is what makes the fix unconditional
    and safe to land without an APR flag: the champion (flag OFF eligibility) sees no
    behavior change for the positive features it already trains on."""
    rng = np.random.default_rng(42)
    n_folds, n_features = 5, 8
    fold_ic_arr = rng.uniform(-1.0, 1.0, size=(n_folds, n_features))
    # Full-sample IC strictly positive for every feature in this equivalence check.
    ic_vector_nd = rng.uniform(0.01, 1.0, size=n_features)

    old_criterion = (fold_ic_arr > 0).sum(axis=0)
    new_criterion = _sign_consistent_wf_pass_count(fold_ic_arr, ic_vector_nd)

    np.testing.assert_array_equal(
        new_criterion,
        old_criterion,
        err_msg="Sign-consistent criterion must be byte-identical to the old "
        "(fold_ic_arr > 0) criterion for ic_sign=1 features (equivalence property).",
    )


def test_multi_feature_mixed_signs_vectorized_correctness():
    """Vectorized correctness across a mix of positive and negative full-sample-sign
    features in a single call -- both the per-symbol and cross-sectional blocks call
    this once per (regime, scale) cell across all non-degenerate features simultaneously."""
    # 2 folds, 3 features: [+, -, +] full-sample signs.
    ic_vector_nd = np.array([0.20, -0.20, 0.05])
    fold_ic_arr = np.array(
        [
            [0.10, -0.10, -0.02],  # feat0 matches(+), feat1 matches(-), feat2 flips
            [0.05, -0.05, 0.01],  # feat0 matches(+), feat1 matches(-), feat2 matches(+)
        ]
    )

    wf_pass_count_nd = _sign_consistent_wf_pass_count(fold_ic_arr, ic_vector_nd)

    assert wf_pass_count_nd.tolist() == [2, 2, 1]


def test_zero_full_sample_sign_treated_as_negative_and_excludes_zero_folds():
    """np.sign(0.0) == 0.0 -- a degenerate exact-zero full-sample IC yields sign 0, so
    `fold_ic * 0` is never > 0 for any fold: no folds pass. This is a safe (fail-closed)
    edge case, not a crash, for a feature that should never have reached this gate with
    a genuinely zero point estimate in the first place (upstream degenerate-feature
    masking excludes exact-zero-variance features before this function is called)."""
    ic_vector_nd = np.array([0.0])
    fold_ic_arr = np.array([[0.10], [-0.10], [0.05]])

    wf_pass_count_nd = _sign_consistent_wf_pass_count(fold_ic_arr, ic_vector_nd)

    assert wf_pass_count_nd.tolist() == [0]
